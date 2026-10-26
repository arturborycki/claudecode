# Supporting transaction time: versions, timestamps, indexing, vacuuming

Transaction time is the one temporal dimension the engine owns end to end:
the DBMS supplies the timestamps, guarantees they agree with the
serialization order, keeps every version, and decides when old versions may
be physically removed. It is also the dimension that overlaps most with
machinery an engine already has (MVCC, recovery, backup), which is both an
opportunity and a source of subtle bugs.

---

## 1. Contract

A transaction-time table stores versions `(key, payload, [tt_start, tt_end))`.

1. **Append-only semantics.** UPDATE creates a new version and closes the
   old one; DELETE only closes the current version. No version is modified
   after its transaction commits, except to close `tt_end` (and to replace a
   provisional XID by a timestamp, see §4).
2. **Serialization consistency.** `tt_start` is the commit time of the
   inserting transaction and `tt_end` the commit time of the
   superseding/deleting one, and timestamp order must agree with the
   serialization order. Only then is every "as of `t`" state a
   transaction-consistent state.
3. **Current semantics.** Every legacy statement sees exactly the current
   state; versioning is invisible unless asked for.
4. **Bounded by now.** No transaction time lies in the future; `tt_end` of a
   current version is the variable `now` / `until changed`.

Query classes to support (Lomet's terminology):

| Class | Example | Access pattern |
|---|---|---|
| "As of" (transaction timeslice) | table state at `t` | for every key, the version alive at `t` |
| "Time travel" | all versions of key `k` in `[t1,t2)` | one key, a time range |
| General transaction-time queries | all versions of many keys in a range | key range × time range |

Applications: auditing and legal/regulatory compliance, reproducing an
analysis on the data as it was, time-series analysis. System uses: snapshot
isolation, online backup, recovery from bad user transactions (§7).

---

## 2. Architecture: layered vs built-in

| Approach | How | Wins | Loses |
|---|---|---|---|
| Layered (middleware / temporal stratum) | layer adds `tt_start`, `tt_end` columns, rewrites temporal DML/queries into plain SQL; typically clusters on `(PK, tt_start, tt_end)` | ships without engine changes; reuses the DBMS | clustering by key makes time travel fast but "as of" slow; grouping by time hurts time travel; timestamping at commit is hard to do correctly from outside (Torp, Snodgrass & Jensen, VLDB J 2000 work through it) |
| Built-in | engine-level versioning in the storage manager | near current-time performance: cheap stamping at update/commit, version compression, time-aware indexes and clustering | requires kernel changes |

The general architecture question (layered / monolithic / extensible) is in
SKILL.md; for transaction time specifically, the built-in approach is the
only one that gets timestamps, CC and storage right together.

---

## 3. Version storage

### 3.1 Timestamps per version

Store **only `tt_start`** in each version; derive `tt_end` from the start of
the next version of the same key. Deletion writes a **delete stub** version.
As-of `t` for a key = the version with the largest `tt_start ≤ t`, unless it
is a stub. A layered implementation stores both ends because its generated
SQL needs them; a built-in one saves space and avoids a second write.

### 3.2 Page layout

Keep the conventional slotted page (B-tree order of current records) so
current-time code paths are unchanged; add a **backward version chain**:
each version points to its predecessor. An as-of read walks the chain from
the current version to the first version with `tt_start ≤ t`. Cost grows with
the number of versions newer than `t`, which is why historical versions need
their own index (§3.3) once history is long.

### 3.3 Time-aware indexing

Without time in the index, as-of cost increases the further back you query.
Options (survey: Salzberg & Tsotras, ACM CSUR 1999):

- **R-tree over (key, time)**: Postgres's original version store
  (Stonebraker, VLDB 1987).
- **TSB-tree** (Lomet & Salzberg, SIGMOD 1989), built on the time split of the
  write-once WOB-tree (Easton, 1986). Node split choices:
  - *key split*: ordinary B-tree split of the key range;
  - *time split* at time `T`: versions whose lifetime ended before `T` move to
    a historical page, versions alive after `T` stay in the current page,
    and versions whose lifetime **spans** `T` are copied into both.
  Every page therefore covers a key × time rectangle, and the index tells
  exactly which pages can contain answers to a key-range × time-range query.
  Despite the copying, total space stays linear in the number of distinct
  versions. Splitting at the current time is convenient; historical pages are
  never updated again and can migrate to cheaper or write-once media. With a
  suitable split policy the TSB-tree gives guarantees for as-of queries.
- **Multiversion B-tree (MVB-tree)** (Becker, Gschwind, Ohler, Seeger &
  Widmayer, VLDB J 1996): asymptotically optimal multiversion B-tree (as-of
  queries cost like a B-tree over the version alive at `t`, with linear space).

Invariants to assert in a TSB/MVB implementation: (i) every version alive at
time `t` with key `k` is reachable via the rectangle containing `(k,t)`;
(ii) a historical page's time range ends before the split time and is never
written again; (iii) the number of version copies is bounded by a constant
factor of distinct versions.

### 3.4 Version compression

Updates usually change few attributes, so store **backward deltas**: the
current version is kept whole (current-time performance and compatibility
unchanged), older versions as diffs against their successor (changed
attributes + location + timestamp). Because a time split copies the
versions spanning the split time and splitting happens at current time, the
newest version on every page is uncompressed, and decompressing any version
needs only its own page.

---

## 4. Timestamping

### 4.1 What a timestamp is

- **XIDs** with a separate XID→time table; for pure MVCC (no time travel),
  an active transaction can map to the list of XIDs committed before it,
  which defines visibility (Rdb).
- **Clock time** for real transaction-time functionality, extended with a
  **sequence number** when clock resolution cannot separate transactions (two
  commits in one chronon must still be ordered).

### 4.2 When to choose it

- *Early* (at transaction start or first write): versions can be stamped
  immediately, but every transaction whose serialization order turns out to
  differ from timestamp order must abort (this is timestamp-ordering CC).
- *At commit* (usual): commit order equals serialization order under strict
  2PL, so stamps are serialization-consistent — but the value is unknown
  while the transaction writes.

### 4.3 Lazy timestamping

Write the XID into each new version at update time; replace XID by the
commit time later.

- *Eager replacement*: revisit and restamp all written versions before
  commit, logging the restamping as more updates — expensive.
- *Lazy replacement* (preferred): after commit, restamp on next access or in
  the background. The XID→time mapping must be **persistent** (survive a
  crash) until every version carrying that XID has been restamped; then the
  mapping entry can be garbage-collected (Lomet et al., "Transaction time
  support inside a database engine", ICDE 2006).

Engine checklist: (1) visibility code must treat "XID, not yet stamped"
versions by consulting the mapping; (2) restamping is a physical change
that must be logged or made idempotent for recovery; (3) the garbage
collector for the mapping needs a cheap "no unstamped versions remain for
XID x" test (e.g., per-page or per-XID reference counts).

> **Beyond EDBS:** PostgreSQL's MVCC follows the same pattern for commit
> *status*: tuples carry XIDs (`xmin`/`xmax`), commit status lives in the
> commit log, and *hint bits* are set lazily on the tuple once status is
> known. `track_commit_timestamp` adds a persistent XID→commit-time map.
> PostgreSQL still cannot answer "as of" queries because VACUUM reclaims
> dead versions and visibility is defined by XID snapshots, not times.
> MariaDB's system-versioned tables offer a "transaction-precise" mode that
> stores transaction IDs in the row start/end columns and resolves them
> through a transaction registry table — an XID→time mapping in production.

### 4.4 User-visible current time

`CURRENT_TIMESTAMP` inside a transaction must be consistent with the
transaction's eventual timestamp. Maintain a feasible window
`[lo, hi]` per transaction:

- each `CURRENT_DATE`/`CURRENT_TIMESTAMP` call intersects the window with the
  granule returned (a DATE constrains only the day, so it rarely bites);
- reading a version stamped `ts` (or written by a transaction that commits
  before us) raises `lo` above `ts` — track the largest timestamp seen;
- at commit, take the earliest instant in the window (respecting the global
  commit order); if the window is empty, abort.

Lomet, Snodgrass & Jensen (2005) implement this with the lock manager.

> **Beyond EDBS:** SQL:2011 only requires that a transaction's timestamp stay
> fixed for the whole transaction and leaves the choice to the
> implementation. Products that stamp with the transaction *begin* time
> (SQL Server documents the begin time of the transaction as the row start
> value) get stamps that need not follow commit order, and must handle a
> transaction trying to supersede a version whose start is later than its
> own stamp (empty or negative period): raise an error or adjust the stamp.
> Test this case explicitly.

### 4.5 Interaction with concurrency control

Synthesis for engine builders (not from the entry):

| CC scheme | Is commit order a serialization order? | Consequence for "as of" states |
|---|---|---|
| Strict 2PL | yes | commit-time stamps give transaction-consistent, serializable historical states |
| Timestamp ordering | yes, by start timestamp | stamp at start; aborts enforce the order |
| MVCC + snapshot isolation | no (SI is not serializable) | an as-of state at `t` is exactly what an SI reader with snapshot `t` sees, but may be a state no serial execution passes through (write skew; the read-only anomaly of Fekete, O'Neil & O'Neil, SIGMOD Record 2004) |
| Serializable SI | no: the equivalent serial order can differ from commit order | same caveat; historical states between two commits can contradict the serial order SSI certified |
| OCC with validation order | validation order is the serial order | stamp at validation |

If historical states must be serializable states, stamp with the
serialization point of the CC protocol, not with wall-clock commit time.

> **Beyond EDBS:** Distributed engines assign commit timestamps from
> TrueTime (Spanner) or hybrid logical clocks (CockroachDB) so that reads
> "at a timestamp" (`AS OF SYSTEM TIME`, snapshot/stale reads) are
> transaction-consistent across nodes, subject to a version GC horizon.

---

## 5. Now and transaction time

Current versions have `tt_end = until changed`. Implement it as a variable
(flag or reserved encoding) bound at query time, not as a stored maximum
value, or at least hide the sentinel from arithmetic and statistics. Index
current and historical versions differently (current: index on start only;
historical: 2-D or TSB-style). Details in `time-models-and-semantics.md` §7.

---

## 6. Temporal vacuuming

A transaction-time database grows without bound. **Vacuuming** is the
strategic, irrevocable physical deletion of obsolete history (the term comes
from Postgres, where the vacuum cleaner originally moved old data to archival
storage; Jensen & Mark (1990) recast it as removal of obsolete information
in temporal databases).

### 6.1 Specifications

Vacuuming specifications state which parts of the history may be removed.

- Phrase them as **what may be deleted**, not what must be retained: "data
  older than 5 years may be deleted" is well formed; "retain everything
  except the last year" is not — next year the retained data would have to
  come back.
- Administrative form (Skyt, Jensen & Mark, DKE 2003): delete expressions `ρ`
  and keep expressions `κ`, run periodically by a vacuuming daemon; **keep
  overrides delete**, and the order of expressions matters. Example: delete
  data corrected more than a year ago (`tt_end < now − 1 year`), delete
  superseded data older than 7 years (`vt_end < now − 7 years`), but keep
  everything for employees with status `Retain`.
- Correlations: if facts in one part of the history are needed to interpret
  others (tax receipts tied to old investments), selective per-item
  vacuuming must keep the correlated older facts; integrity must be rechecked.

### 6.2 Formal model (Toman; Skyt et al.)

Let history `H = ⟨S0, …, Sk⟩`. A vacuuming specification is a view
`E : H → H'` (the **residual history**). Two questions:

1. **Well-formedness = self-maintainability.** Only `E(H)` is stored, so it
   must be updatable when a new state arrives:
   `E(H;S) = Δ(E(H), S)` for some query `Δ`, starting from a constant `∅` for
   the empty history. `(∅, Δ)` is a *realization* of `E`.
2. **Supported queries.** Query `Q` is answerable iff `Q(H) = Q'(E(H))` for
   some reformulation `Q'`. `E` is then a *faithful history encoding* for
   `Q`, and `(∅, Δ, Q')` is the *expiration operator* of `Q`.

Space is measured against `|H|`, the active data domain `|D_H|`, and the
history length `|T_H|`. The identity view is always a (useless) faithful
encoding, linear in `|T_H|`; the interesting classes are encodings bounded by
**O(1)** or **O(log |T_H|)** in history length (still dependent on `|D_H|`).

Limits:

- With an arbitrary number of ad hoc first-order queries, no effective
  vacuuming is possible (FO queries can characterise any finite structure).
  So either vacuum by **administrative policy** (ad hoc queries allowed;
  queries that touch expired data must fail or be flagged approximate in a
  predefined way) or do **query-driven expiration** for a fixed, known set of
  queries.
- **Valid-time** databases allow arbitrary updates of the past, so the only
  faithful encodings are lossless; vacuuming buys nothing (the same holds
  even if updates are restricted to insertions). Vacuuming is a
  transaction-time concept.

### 6.3 Language support

- TSQL2: a `VACUUM` clause on the table, e.g. `VACUUM NOBIND (DATE 'now - 7
  days')` restricts permissible queries to the last 7 days relative to query
  time (`NOBIND` keeps `now` unbound), while `VACUUM DATE '12 Sep 2007'`
  fixes an absolute cutoff.
- Tuple-level expiration: `INSERT … EXPIRES TIMESTAMP '…'` (Schmidt, Jensen &
  Šaltenis, ICDE 2006).

### 6.4 Connections

- The same "keep a bounded encoding of the past" idea underlies
  **historyless temporal integrity checking** (Chomicki's bounded history
  encoding; see `sql2011-temporal-and-tsql2.md` §4).
- An expiration operator for a query is a **synopsis** for that query over a
  stream, and space bounds transfer (see `stream-processing-engines`).
- Vacuuming of obsolete **schema versions** (when no data stored under that
  version remains and no transaction time refers to its active period) is the
  schema-level analogue and an open problem when combined with data
  vacuuming.

---

## 7. Other uses of the version store

- **Snapshot isolation**: recent versions serve SI readers; versions kept only
  for CC can be garbage-collected faster than versions kept for time travel.
- **Online backup**: an old state can serve as a backup only if it is stored
  apart from the current state's medium and the media-recovery log that rolls
  it forward is kept on a separate device as well. TSB time splits can move
  historical pages to the backup medium incrementally (Lomet & Salzberg,
  VLDB 1993).
- **Bad user transactions**: point-in-time recovery from online versions
  instead of restore + roll-forward (Oracle Flashback); tracking read
  dependencies identifies exactly which later transactions must also be
  removed (Lomet, Vagena & Barga, SIGMOD 2006).

---

## 8. Beyond EDBS: production systems

> **Beyond EDBS — MVCC time travel.** Original Postgres used no-overwrite
> storage and supported time travel; it was removed early in PostgreSQL's
> history, leaving MVCC versions purely for concurrency. Oracle Flashback
> Query reads old versions from undo (bounded by undo retention) and Flashback
> Data Archive keeps history long-term. SQL Server and DB2 implement
> system-versioned tables as a current table plus a history table populated
> by UPDATE/DELETE; SQL Server additionally supports a history retention
> policy (an administrative vacuuming specification).

> **Beyond EDBS — Lakehouse snapshots.** Apache Iceberg and Delta Lake are
> transaction-time stores at **table-snapshot** granularity:
> - Iceberg: every commit atomically installs a new metadata file whose
>   snapshot references a manifest list; the snapshot log maps commit
>   timestamps to snapshot ids, so `AS OF` timestamp resolves to the latest
>   snapshot committed at or before it, or a snapshot id/tag/branch is named
>   directly. `expire_snapshots` is the vacuuming operation: it drops old
>   snapshots and deletes data files no longer reachable; time travel to an
>   expired snapshot then fails (the "fail in a predefined manner" policy).
> - Delta Lake: an ordered log of JSON commit files plus periodic Parquet
>   checkpoints; `VERSION AS OF` / `TIMESTAMP AS OF` select a log version;
>   `VACUUM` deletes unreferenced data files older than a retention threshold,
>   after which older versions are no longer readable; log entries have their
>   own retention.
> - Both give "as of" queries cheaply (read an old manifest) but not
>   efficient per-key "time travel" or general transaction-time queries:
>   there is no version index by key, so row histories require scanning
>   several snapshots or a change feed (Delta Change Data Feed, Iceberg
>   changelog/incremental reads). In EDBS terms they are clustered by time,
>   which favours as-of over time travel — the mirror image of the layered
>   `(PK, start)` clustering.
> - The timestamp→snapshot mapping is only as good as the commit clock.
>   Verify that commit timestamps are monotone across writers before relying
>   on timestamp-based time travel for audit.

Sources: EDBS entries Supporting Transaction Time Databases (p.3857),
Transaction Time (p.4200), Now in Temporal Databases (p.2517), Temporal
Vacuuming (p.4040), TSQL2 (p.4246), Temporal Database (p.3945), Timeslice
Operator (p.4159), Temporal Integrity Constraints (p.3980).
