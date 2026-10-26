# Auditing, forensics, intrusion detection, inference control, privacy, and compliance

Scope: what an engine's audit subsystem must record and how to protect it
(tamper-evident logs, hash chaining); forensic residue in storage structures
and how to remove it; intrusion and anomaly detection inside the DBMS
(query profiles, SQL injection, query floods); insider threats; inference
control in statistical databases; privacy-preserving (Hippocratic) DBMS
mechanisms; regulatory compliance (retention minima and maxima, WORM,
guaranteed deletion vs immutable logs); secure DBMS development lifecycle.

---

## 1. Audit subsystem

### 1.1 Purpose and contents

Goals: verify compliance with policy, trace violations, detect anomalous
access. Typical audit questions an engine must be able to answer:
- statements that modified more than N rows, with their text;
- which authorization ids ran SELECTs on table T during a time window;
- which rows of T had column c modified more than k times in 12 months;
- is today's update workload similar to the normal profile.

An audit record should carry: authorization id (and effective role set),
session id, client/network identity, timestamp, statement text (or a
normalized digest with bind values handled per policy), objects touched
(table/column, optionally row ids), privilege used, outcome (success, denied,
error, **aborted** — aborted transactions vanish from data and WAL effect but
must not vanish from audit), rows affected/returned, and for updates/deletes
optionally before-images. Also: logins and failed logins, privilege and role
changes, policy changes, audit-configuration changes (audit the auditor).

### 1.2 Mechanism options

| Mechanism | Strength | Weakness |
|---|---|---|
| Native statement/object audit (policy-driven) | Captures reads, denials, context; configurable granularity (per object, per row, first access per session vs every access) | Overhead if written synchronously to tables; if stored in-database the DBA can alter it |
| User-level triggers | Easy, per-row before/after images | Cannot see SELECTs; row-level triggers are expensive; bypassable by owners (disable trigger, TRUNCATE, bulk load) |
| Transaction log (WAL) mining | Free, complete for writes, has before/after images | No reads; little context; recycled/circular so retention is wrong; reconstructing past state needs PITR replay — slow |
| Transaction-time (persistent, "as-of") database | Full history queryable as of any time; deletes never destroy data | Storage growth; still no reads; must combine with query logs |
| External audit sink (OS file, syslog, append-only service) | Out of reach of in-database privileges | Delivery guarantees; ordering with commits; confidentiality of the log itself |

Engine design rules:
1. **Where**: emit audit records from the executor/authorization layer (the
   point where the privilege check succeeded or failed), not from the parser —
   a statement parsed but never executed, or a view that expands to many
   tables, must be recorded by what actually ran.
2. **Atomicity vs completeness**: data effects are rolled back on abort, audit
   records of the attempt must not be. Write audit through a channel that is
   not part of the user transaction (autonomous write, separate log stream).
3. **Ordering**: record a commit sequence number/LSN so audit and data
   history can be joined; an audit record for a write should be durable no
   later than the commit it describes, if the policy demands no unaudited
   commits (synchronous audit on the commit path — costs latency like a second
   WAL).
4. **Volume**: offer coarse modes (session-level, first-access-per-object) and
   sampling only where policy allows; read auditing of large scans should
   record predicates and row counts, not every row id, unless required.
5. **Retention**: audit retention is set by regulation and is usually far
   longer than WAL retention; audit data is itself sensitive (who looked at
   what, SQL text with literals) and must be destroyed when its retention ends.
6. **Confidentiality**: reading audit logs is a highly privileged operation;
   literals in SQL text can contain personal data — consider redaction or
   encryption of the audit store (searchable encrypted audit logs: Waters,
   Balfanz, Durfee, Smetters, NDSS 2004).

### 1.3 Auditing disclosure (reads)

Modifications are easy to audit; disclosure is not, because information can be
inferred from a sequence of queries none of which returns the target value
(aggregate queries hiding one individual). Audit-query approach (Agrawal,
Bayardo, Faloutsos, Kiernan, Rantzau, Srikant, VLDB 2004, "Auditing compliance
with a Hippocratic database"): given an audit expression describing the
sensitive data (e.g. "Alice's diagnosis"), identify logged queries that were
*suspicious*, i.e. whose answers depended on that data, by re-evaluating them
against the database state as of their execution time (needs a backlog /
temporal versioning of data plus the query log).

### 1.4 Tamper-evident audit logs

The DBA and other privileged insiders must not be able to alter audit history
undetectably. Options, in increasing strength:
- append-only storage + privileges (prevents casual tampering only);
- WORM media or soft-WORM storage (see §6);
- **cryptographic chaining** (Schneier & Kelsey, TISSEC 1999): log entry i is
  protected with key `A_i`, where `A_{i+1} = h(A_i)` and `A_i` is erased after
  use (forward integrity: compromise at time t cannot forge entries before t);
  each entry carries a hash-chain value `Y_i = h(Y_{i-1} || E_i || ...)` and a
  MAC under `A_i`; a verifier who knows `A_0` recomputes everything;
- **external anchoring / notarization**: periodically send the chain head to a
  trusted notary or publish it. Snodgrass, Yao, Collberg (VLDB 2004) hash each
  tuple version into a running chain in a transaction-time database and notarize
  digests externally; validation re-computes and compares, and later forensic
  analysis can bound *where and when* tampering happened.
- > **Beyond EDBS:** Crosby & Wallach (USENIX Security 2009) use a
  history tree (Merkle-tree-based log) giving O(log n) proofs that one log
  version is a prefix of another and that an entry is included. Products now
  ship ledger features: SQL Server ledger tables (2022) hash-chain row
  versions into blocks whose digests can be stored externally; Oracle offers
  blockchain/immutable tables. Treat these as tamper-*evident*, not
  tamper-proof: detection still depends on digests kept outside the
  adversary's control.

Hash-chain verification algorithm (sketch):
```
verify(log, anchor_head, anchor_index):
  y := Y_0
  for i in 1..n:
     y := h(y || canonical(E_i))
     if i == anchor_index and y != anchor_head: report tamper in (prev_anchor, i]
  # Truncation: detected only if a later anchor exists or the length is anchored.
```

---

## 2. Database forensics and data remanence

Forensic analysis validates hypotheses about past events from any component:
table storage, indexes, WAL, undo, temp files, caches, catalogs, backups. The
engine-builder's concern is the inverse: *expired data persists*.

Lifecycle: active → expired (deleted/updated away, no operation will use it
again) → overwritten. Between expiry and overwrite the data is **database
slack** (inside DB files) or **file-system slack** (after the DB returns space
to the FS).

Residue sources in a typical engine (Stahlberg, Miklau, Levine, SIGMOD 2007):
- deleted heap tuples only flagged (delete bit, xmax set); MVCC old versions
  until vacuum;
- variable-length updates in place leave the tail of the longer old value;
- B+-tree leaf entries removed logically but bytes not zeroed; deleted keys
  in internal nodes as separators;
- VACUUM/compaction copies live tuples elsewhere and truncates the file,
  returning old pages, with old data, to the file system;
- temp relations, sort runs, hash spill files;
- WAL/redo with full before and after images, recycled circularly; archived WAL
  kept forever;
- undo/rollback segments; buffer-pool pages in swap or core dumps;
- backups.

Forensic transparency desiderata (Stahlberg et al.):
1. **Clarity**: the effect of each operation on active/expired state is clear.
2. **Purposeful retention**: only active records are retained.
3. **Complete removal**: expired records are removed within a short, bounded
   time.

Removal techniques:
- **Overwrite** on delete/compaction (zero the freed bytes in pages, zero
  freed index entries, zero before truncating files). SQLite's
  `secure_delete` pragma is a production example. Synchronous overwrite costs
  I/O; asynchronous overwriting during idle time leaves a window.
- **Encrypt and destroy the key** (crypto-erasure): the only practical way to
  reach WAL archives and backups. Granularity of keys determines what can be
  erased independently (per table, tenant, data subject, time window).
- WAL: either full-page images and before-images are encrypted with keys that
  rotate on a schedule shorter than the removal bound, or the WAL is not
  retained past the bound (conflicts with PITR — make the conflict explicit).
- > **Beyond EDBS:** **history independence** (Micciancio 1997; Naor &
  Teague 2001; applied to file systems by Bajaj & Sion, CCS 2013, cited in
  EDBS) requires that the physical representation reveal nothing beyond the
  current logical content — e.g. the layout of a hash table or B-tree must not
  depend on insertion/deletion order. Standard B-trees, slotted pages and LSM
  levels are *not* history independent: page split points, free-space
  fragmentation and SSTable boundaries record history.

---

## 3. Intrusion detection inside the DBMS

### 3.1 Architecture and methods

IDS = event collector + analysis engine + response module. For a DBMS the
event stream is the audit/query log, at the application layer (as opposed to
OS or network IDSs). Attack categories: external break-in, masquerader
(insider using another's identity), penetration (direct policy violation),
leakage, denial of service, malicious use.

| Approach | Model | Pros | Cons |
|---|---|---|---|
| Misuse (signature) detection | Rules/state-transition models of known attacks (e.g. USTAT-style state transition analysis; MIDAS, IDES rules) | Precise for known attacks, cheap | Misses novel attacks; rule bases grow unmanageable |
| Static anomaly detection | Integrity of static parts (e.g. Tripwire over files) | Simple | Only for content that should not change |
| Dynamic anomaly detection | Profile normal behaviour statistically (NIDES-style), flag deviation | Catches novel attacks; self-configuring | False positives; profile drift; training on poisoned data |

### 3.2 Query-profile anomaly detection for DBMSs

RBAC-based detection (Bertino, Kamra, Terzi, ACSAC 2005; extended by Kamra,
Terzi, Bertino, VLDB J 2008): represent each SQL statement by a feature tuple
(command type, relations referenced, attributes referenced per relation —
at coarse/medium/fine granularity); train a classifier (naive Bayes) that
predicts the *role* from the features; at run time, if the predicted role
differs from the session's actual role, raise an alarm. Roles give a small,
stable set of classes, which makes profiles tractable compared to per-user
profiles. Engine hooks: features are available after binding; the check can run
synchronously (block) or asynchronously (alert).

Other signals: query floods (Bertino, Leggieri, Terzi 2004) as application-
level DoS — detect by rate per (user, statement template) against a profile;
time signatures for real-time DBs (Lee, Stankovic, Son 2000); result-size
anomalies (an account that normally reads 10 rows reads 10M — exfiltration).

### 3.3 SQL injection (SQLIA)

Root cause: application code concatenates untrusted input into SQL text, so
data is parsed as code. Effects range from data leakage to full bypass of
application-level authorization.

Engine-side defenses (the engine cannot fix the application, but it can make
the safe path the easy path and detect the unsafe one):
1. **Parameterized statements / prepared statements** over a protocol that
   separates statement text from bind values (PostgreSQL extended query
   protocol, server-side prepare). Bind values are never parsed.
2. Disable multi-statement execution in a single call by default (stacked
   queries).
3. Least privilege for application accounts; RLS so that injection yields only
   the current user's rows.
4. **Statement-template allow-listing**: normalize statements to templates
   (literals stripped) and alert on templates never seen from that application;
   equivalent to comparing parse-tree shape against the intended query
   (parse-tree validation, e.g. SQLGuard; model-based AMNESIA, Halfond & Orso
   2005).
5. Uniform, non-verbose errors to clients (error-based extraction relies on
   messages that echo data), and resistance to time-based blind injection is
   largely an application concern.
6. Fuzz the parser itself (`sql-frontend`, `query-engine-testing`): injection
   payloads exercise rarely used grammar.

### 3.4 Response and self-protection

Responses: log, alert, require re-authentication, drop the session, suspend
the role, or block the statement. The IDS is itself an attack target: its
profiles and logs need the same tamper protection as audit logs. Real-time
response on the query path must be bounded in latency.

---

## 4. Insider threats

Malicious insider (CERT definition): a current or former employee, contractor
or partner with authorized access who intentionally misuses it against
confidentiality, integrity or availability. Main classes: IT sabotage, theft
of intellectual property, fraud (unauthorized modification of data for gain);
also unauthorized disclosure and curiosity browsing (e.g. reading celebrities'
medical records).

DBMS-relevant controls:
- **Separation of duties between DBA and security administrator/auditor**:
  the DBA manages storage and performance but cannot read protected data,
  change policies or alter audit; the auditor can read audit but not data.
  Commercial realisations exist (e.g. Oracle Database Vault realms). In engines
  where "superuser" bypasses everything, separation is impossible — design an
  administrative privilege lattice instead of a single superuser bit.
- Encryption with keys held outside DBA reach (client-side or HSM with
  separate custodians) for data the DBA must not read.
- Tamper-evident audit with external anchors; alerting on audit configuration
  changes.
- Two-person rules for high-risk operations (policy changes, key export, audit
  disable).
- Anomaly detection tuned to legitimate-credential misuse (volume, time of
  day, unusual tables for the role).
- Revocation that takes effect immediately in long-lived sessions and pooled
  connections.

---

## 5. Inference control in statistical databases (SDC)

Goal: publish or answer aggregate queries without revealing confidential values
of individuals, with minimal accuracy loss. Three sub-areas.

### 5.1 Tabular data

Attacks on published tables: external (a cell with one respondent discloses
their value when a magnitude table is also published), internal (two
respondents learn each other's value), dominance (a dominant contributor bounds
others). Sensitivity rules: **(n, k) dominance** — sensitive if ≤ n
respondents contribute ≥ k% of the cell; **p%-rule** — sensitive if some
respondent can estimate another's contribution within p%. Protection: cell
suppression (primary + secondary suppressions so primaries cannot be
recomputed from marginals — a MILP/network-flow optimization), controlled
rounding, controlled tabular adjustment (closest perturbed table that protects
all sensitive cells; usually less information loss than suppression).

### 5.2 Queryable (on-line) statistical databases — the engine case

| Control | Mechanism | Known weakness |
|---|---|---|
| Query-set-size restriction | Refuse if `|q| < k` or `|q| > N − k` | Defeated by **trackers** (Schlörer 1975/1980; Denning, Denning, Schwartz, TODS 1979) |
| Query-set-overlap control | Refuse queries overlapping previous ones by more than r records | Per-user state; colluding users; restrictive |
| Auditing (Chin & Ozsoyoglu, TSE 1982) | Keep the system of answered queries; refuse a query if answering would make some individual's value derivable | Expensive in general; denials themselves leak (see beyond-EDBS) |
| Perturbation (input or output) | Add noise to data or to answers (e.g. Duncan & Mukherjee, JASA 2000, against trackers) | Repeated queries average noise away unless noise is deterministic per query or budgeted |
| Camouflage (CVC; Gopal, Garfinkel, Goes, Oper. Res. 2002) | Answer with an interval guaranteed to contain the true answer, computed over a compact set of vectors containing the true data | Interval answers only |

Tracker example (individual tracker): suppose `C = A ∧ B` identifies a single
individual, so `count(C)` is refused. Using `T = A ∧ ¬B` (large enough to be
answered): `count(C) = count(A) − count(T)` and
`sum(salary | C) = sum(salary | A) − sum(salary | T)`. General trackers make
any small query answerable with a few padded queries; this is why size
restriction alone is insufficient.

### 5.3 Microdata

Release protected record-level data V' from V such that disclosure risk is low
and analytical results are close. Masking: perturbative (noise addition,
microaggregation, rank swapping, rounding, PRAM) or non-perturbative
(sampling, global recoding, top/bottom coding, local suppression); or
synthetic data. Risk/utility trade-off assessed with SDC scores, k-anonymity,
R-U maps. Knowing the algorithm enables algorithm-specific attacks, and the
output often reveals which algorithm was used.

> **Beyond EDBS:** Differential privacy (Dwork, McSherry, Nissim, Smith,
> TCC 2006) replaced ad hoc query restriction in practice: each query result
> is perturbed (e.g. Laplace noise scaled to sensitivity/ε) and a privacy
> budget ε is consumed per query, giving a guarantee independent of the
> attacker's background knowledge and robust to composition. Kenthapadi,
> Mishra, Nissim (PODS 2005) showed that naive auditing leaks through the
> *decision* to deny, and proposed simulatable auditing (deny based only on
> past queries and answers, not on the data). Engine integration points: a
> query rewriter that rejects non-aggregate queries on protected tables,
> computes sensitivity of aggregates (bounded contribution per individual —
> requires an entity-id column and per-entity clamping), adds noise in the
> final aggregate, and maintains a per-principal budget ledger durably and
> atomically with result release.

---

## 6. Regulatory compliance and the engine

Recurrent regulatory requirements (HIPAA, GLBA, SOX, EU data retention rules,
GDPR, national corporate-governance codes): confidentiality and
de-identification, breach notification, periodic audits, **minimum retention**
(e.g. SOX: audit reports kept 7 years; EU data retention directive: some
communications data at least 6 months), **maximum retention** followed by
**guaranteed, irrecoverable deletion**, and integrity of records.

### 6.1 WORM and compliance storage

WORM semantics: once written, a record cannot be undetectably altered or
deleted before its retention period ends, even by an adversary with physical
access. Implementations: optical/tape WORM media; "soft-WORM" on rewritable
disks enforced in firmware/software (content-addressed stores where the address
is a hash of content and per-record retention lives in a descriptor; file
systems with retention-locked files); trusted hardware at the storage site to
resist insiders.

Engine implications:
- Records must be *term-immutable* (immutable for a retention period), but an
  engine's own storage is mutable (in-place updates, compaction, page
  rewrites). Put WORM below an append-only representation: an insert-only
  table or log-structured segments sealed and handed to WORM; indexes on WORM
  data must themselves be trustworthy — the **fossilized index** (Zhu & Hsu,
  SIGMOD 2005) is an index whose structure, once written, can only be extended
  (so an insider cannot hide a record by rewriting the index while the record
  stays on WORM).
- Commit of a compliance record = durable on WORM, not merely in WAL.
- Retention metadata (per record or per segment) drives an expiry process that
  must be audited and must produce irrecoverable deletion where the maximum
  retention applies.

### 6.2 The central conflict: erasure vs immutability

Right to erasure / maximum retention demands that personal data become
irrecoverable; audit, WORM, WAL archives, backups, replicas and ledgers demand
that history be immutable. Practical resolution patterns:

| Pattern | How | Residual risk |
|---|---|---|
| Crypto-shredding | Encrypt personal data under per-subject (or per-tenant/per-period) keys; erase = destroy key; immutable logs keep ciphertext | Key granularity; key backups must also expire; metadata (sizes, timestamps, hashes) remain |
| Pseudonymization with separate mapping table | Immutable stores hold pseudonyms; the mapping table is mutable and erasable | Re-identification from quasi-identifiers in the immutable data |
| Hash-chain of digests, data stored separately | Chain over salted digests of records; record bodies deletable; chain verifies remaining records and proves deletion happened at a point | Salted digests of low-entropy data must use secret salt to avoid dictionary attacks |
| Retention-aware segmenting | Partition logs/backups by expiry date; drop whole segments when expired | Segments mixing subjects must wait for the longest retention |

Secure deletion by overwrite or key destruction still leaves **side effects**
of past existence (index shape, free-space layout, statistics, sequence
values); EDBS notes these can be recovered from current system state, and
history independence / untraceable deletion is needed to remove them.

### 6.3 Other research-to-engine links

- Privacy-preserving data publishing (de-identification before sharing):
  k-anonymity-style generalization; optimal k-anonymization (Bayardo &
  Agrawal, ICDE 2005).
- Verifiable computation for outsourced compliance (prohibitively expensive in
  general; specialized range-query verification is cheaper).
- Audit frameworks where policies are written in a high-level language and
  auto-enforced (Cederquist et al., 2007).

---

## 7. Privacy-preserving (Hippocratic) DBMS — engine components

From the Hippocratic database strawman (Agrawal, Kiernan, Srikant, Xu, VLDB
2002): privacy policy → privacy-metadata creator → privacy metadata
(per-attribute purposes, external recipients, retention periods, authorized
users); privacy-constraint validator at data collection (does the collecting
application's policy match the user's preferences); data-accuracy analyzer;
attribute-level and record-level access control by purpose (query rewriting,
see the authorization reference); query intrusion detector (compares queries
against the access profile of the purpose); audit trail; data-retention
manager (deletes data whose purposes have all expired); encryption support.
Hippocratic PostgreSQL (Padma, Silva, Arshad, Aref, ICDE 2009) and DB2-based
prototypes demonstrate the rewrite approach. Open problems: enforcing policy
after data leaves the DBMS, assigning purposes to programs automatically,
limited retention across transactional history (Kirchberg & Link, HICSS 2010).

---

## 8. Secure DBMS development lifecycle

Two distinct problems: (a) building a *general-purpose* secure DBMS (the DBMS
is the application; nothing is known about future workloads; security is a
non-functional requirement parameterized by the chosen model, e.g. RBAC or
MLS); (b) building an application that embeds a database, where security rules
are application specific and reflected in schema and policies.

Methodology elements applicable to engine development (Fernandez et al.
patterns methodology, 2006; Jürjens' UMLsec, 2004):
- domain analysis: regulatory constraints become global policies; decide
  whether specialised architectures (MLS, enclaves) are needed;
- requirements: per use case (query, update, admin, backup, replication) list
  threats per activity; prune by risk;
- analysis: express policies in an abstract model (access matrix, RBAC,
  lattice) before choosing mechanisms;
- design: pick enforcement mechanisms — EDBS names the two classic choices,
  query modification (INGRES) and views (System R); define the layering
  (OS security services vs DBMS services vs an application server that unifies
  security across databases), and map constraints between layers;
- implementation: security rules as code units; COTS crypto libraries;
  performance iteration;
- assurance: verifying each pattern does not verify their composition — test
  composition explicitly (e.g. RLS × views × MVs × replication × backup).
- mapping from a conceptual security model (classes in UML/OCL) to SQL
  authorization (relations, views, label columns) must preserve every
  conceptual constraint; implementation may only add constraints. Model-driven
  tools generate SQL policies (e.g. OSCL2 to Oracle Label Security).

> **Beyond EDBS:** in engine projects this maps onto threat modelling (e.g.
> STRIDE per data-flow), security review gates for every new access path,
> continuous fuzzing of the network protocol and parser, privilege-separated
> processes for pre-authentication code, and memory-safe languages for
> parsing untrusted input.

---

Sources: Auditing and Forensic Analysis (p.218); Intrusion Detection Technology
(p.2031); Protection from Insider Threats (p.2899); Inference Control in
Statistical Databases (p.1916); Privacy-Preserving DBMSs (p.2822); Regulatory
Compliance in Data Management (p.3141); Storage Security (p.3760); Secure
Database Development (p.3346); Database Security (p.974).
