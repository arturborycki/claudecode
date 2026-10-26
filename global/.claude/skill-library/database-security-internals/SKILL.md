---
name: database-security-internals
description: "Use when designing, implementing or reviewing security machinery inside a DBMS: privilege enforcement (GRANT/REVOKE, grant option, cascading revocation, RBAC, separation of duty, temporal access control), row-level security and query modification, MAC/multilevel security and covert channels in concurrency control, authentication, encryption at rest and key rotation, querying encrypted data, verifiable query results, enclaves, tamper-evident audit, inference control, SQL injection, retention and erasure. Triggers on REVOKE CASCADE, privilege, role, RBAC, RLS, VPD, security barrier, leakproof, Bell-LaPadula, polyinstantiation, covert channel, TDE, key rotation, crypto-shredding, CryptDB, order-preserving encryption, Paillier, Merkle tree, SGX, audit log, hash chain, differential privacy, SQL injection, WORM, right to erasure. Apply even when phrased as 'multi-tenant isolation', 'can tenant A see tenant B', 'encrypt the WAL' or 'make the audit trail trustworthy'."
---

# Database Security Internals

This skill owns the engine's **reference monitor and everything that protects
data below and around it**: where authorization is checked and injected into
plans, how locks/aborts/unique indexes leak across security boundaries, how
pages/WAL/backups are encrypted and keyed, how results and history are made
verifiable, and how audit, retention and erasure are made trustworthy. The
single most important idea: **every mechanism that lets one principal observe
an effect of another's data — a predicate, an error, a wait, an abort, a
statistic, a page — is an access path that must be mediated or explicitly
accepted as leakage.**

## Mental model

```
 client --TLS/auth--> security context (user, active roles, purpose, labels, policy epoch)
  parse -> bind [object/column privileges] -> rewrite [views, RLS quals, masks, purpose]
  -> optimize [security barriers, no leaky pushdown] -> plan cache [keyed by context]
  -> execute [WITH CHECK, label checks, audit at decision point]
  -> CC/commit [no cross-level waits/aborts] -> buffer pool (plaintext)
  -> storage manager [AEAD pages, WAL, temp, backups] -> disk / WORM / outsourced store
 side channels: errors, timing, lock waits, aborts, stats/EXPLAIN, unique/FK checks, layout
```
Trust boundaries: user vs engine (authorization, inference); engine vs storage/
operator (encryption, integrity, enclaves); engine vs its own admins (SoD, audit).

## Core invariants

1. **Complete mediation**: every path that reads/writes relation data (DML,
   COPY/bulk, utilities, catalog functions, FDWs, replication, EXPLAIN, stats
   views) carries a security context and passes the same checks.
2. **Column privileges cover all references**: a predicate, join key, ORDER BY
   or GROUP BY on a column is a read of it.
3. **Policy before untrusted code**: no leaky function (error, side effect,
   timing) sees a row before it passes the RLS policy, unless proven leakproof.
4. **Writes satisfy the policy after modification** (WITH CHECK/block
   predicate) on INSERT, UPDATE, MERGE and upsert paths.
5. **Plan/result caches are keyed by security context** and invalidated by
   GRANT/REVOKE/ALTER POLICY/role-membership changes.
6. **Revocation semantics are defined and tested** (reachability or timestamp);
   RESTRICT fails if anything is abandoned; CASCADE drops dependents too.
7. **Existence is not an oracle**: "absent" vs "not permitted" look identical;
   unique/FK checks are scoped to visible rows (or polyinstantiate).
8. **Cross-level/tenant noninterference**: another level's or tenant's
   transaction never delays, aborts or changes the result of yours; deadlock/SSI
   victims are chosen on the dominating side.
9. **At-rest encryption covers every persistent byte**: data, indexes, WAL,
   undo, temp/spill, backups, archives, replication streams, dumps.
10. **(key, nonce) is never reused**; page rewrites without an LSN change get a
    fresh nonce or use a tweakable deterministic mode.
11. **Integrity needs a key or an external anchor**; a hash beside the data
    only catches accidents.
12. **Audit records survive aborts**, are emitted at the authorization decision
    point, and are durable no later than the commit they describe when required.
13. **Secrets never reach logs** (passwords, keys, redacted literals).
14. **Deletion is bounded**: expired data leaves pages, indexes, files, WAL and
    backups within a stated bound, or is crypto-shredded.

## Design space & trade-offs

| Decision | Option | Wins when | Cost / risk |
|---|---|---|---|
| Fine-grained enforcement | Views (System R) | Few static policies, column hiding | View explosion; update-through-view rules |
| | Query modification / RLS (INGRES, VPD, PG policies) | Per-row/tenant policies as data | Barrier-aware optimizer; Truman-model surprises; cache keying |
| Revocation | SQL reachability | Simple, standard | Grant laundering via later regrants |
| | Timestamp-recursive (Griffiths–Wade/Fagin) | "As if never granted" | Per-edge timestamps |
| | Non-cascading (re-attribute) | Org changes w/o collateral loss | Revoker silently inherits grants |
| MAC architecture | Trusted subject | One engine, performance | Whole engine in TCB |
| | Kernelized single-level fragments | Small TCB | Recombination; read-down CC |
| At-rest encryption | Page/file TDE | Default; transparent to optimizer, indexes, compression | No protection from SQL users/DBA; plaintext buffer pool |
| | Column/cell, server keys | Separate key domain, per-subject shredding | Indexing, compression, statistics complications |
| | Client-side DET/RND/OPE/HOM | Untrusted server/operator | DET/OPE/access-pattern leakage; limited SQL |
| Page cipher mode | AES-GCM | Room for nonce+tag; integrity needed | Nonce management |
| | AES-XTS | No spare bytes | Deterministic per (page, content); no integrity |
| Encrypted predicates | Bucketization | Ranges with tunable leakage | Superset results, client filtering |
| | OPE/DET indexes | Index-friendly | Inference attacks on low-entropy columns |
| | Enclave/SCPU operator | Rich predicates on secrets | Side channels, crossing cost, attestation |
| Result verification | Merkle tree + boundary tuples | Ranges, dynamic data | O(log n) proofs; boundary disclosure |
| Audit integrity | Append-only + privileges | Low threat | DBA can rewrite |
| | Hash chain + external anchor | Insider threat, compliance | Anchor custody; truncation needs anchored length |
| Statistical access | Size restriction / differential privacy | DP for aggregate-only access | Trackers defeat size limits; DP costs noise + budget ledger |

## Algorithms that matter

- **SQL REVOKE** per (object, privilege): delete edge g→r; BFS from owner over
  grant-option edges marks live grantors; edges from non-live grantors are
  abandoned; RESTRICT → error, CASCADE → delete them plus dependent views/
  constraints and invalidate plans. O(V+E).
- **RLS rewrite**: after view expansion, at each protected scan AND (OR of
  permissive quals) with all restrictive quals for the command and roles; wrap
  as a security barrier; add WITH CHECK on new tuples; let user quals cross the
  barrier only if every function in them is leakproof.
- **Secure read-down** (MLS or tenant isolation): lower-level reads take no
  lock a lower writer could wait on; read the latest version committed before
  the reader's level snapshot; resolve cross-level rw-conflicts by ordering the
  higher reader first, never by aborting the lower writer; GC horizon must not
  depend observably on high activity.
- **Page TDE**: nonce = (page_no, LSN or persisted write counter); AEAD with
  AAD = (file id, page no, key version, LSN); verify-then-decrypt on read.
  Online DEK rotation: per-page key version, background re-encrypt through the
  WAL-logged write path, destroy old key below the WAL/backup low-water mark.
- **Merkle range proof**: tree over key-sorted tuples; return results, both
  boundary tuples and sibling digests; verifier recomputes the signed root,
  checks boundaries straddle the range and leaves are contiguous. O(k + log n).
- **Tamper-evident audit** (Schneier–Kelsey): `Y_i = h(Y_{i-1} || E_i)`, MAC
  under evolving key `A_{i+1} = h(A_i)` with old keys erased, chain heads
  anchored externally; tampering localized between anchors.
- **Tracker**: refused `count(A∧B)` = answered `count(A)` − `count(A∧¬B)`.

## Failure modes & classic bugs

- Unmediated new path (bulk export, sampling, system function, FDW); plan or
  pooled-session role surviving REVOKE; SECURITY DEFINER using caller's path.
- Leaky pushdown (UDF raising its argument below the policy filter); error,
  unique/FK/upsert, stats/MCV/EXPLAIN and timing oracles on hidden rows.
- REVOKE checking "has an incoming edge" instead of reachability from owner,
  so grant-option cycles keep privileges alive.
- Cross-tenant lock waits/aborts and global unique indexes as covert channels.
- Plaintext WAL/spill/archive/core under "TDE"; nonce reuse after crash or
  hint-bit rewrite; unauthenticated encryption; page replay; DET/OPE on
  low-entropy columns; onions peeled by ad-hoc queries.
- Audit inside the user transaction (lost on abort), silently disableable by the
  DBA, passwords in statement logs; "deleted" data in slack, index entries,
  truncated files, WAL archives and backups.

## Implementation checklist (C/C++/Rust)

- Immutable per-statement `SecurityContext { user, active_roles, purpose,
  labels, policy_epoch }`; relation-open APIs require it (Rust: mandatory
  parameter/typestate; C++: no default overload).
- ACLs as compact per-object arrays (grantee, grantor, privilege bitset, grant-
  option bitset); per-session role-closure cache invalidated by catalog epoch;
  cycle check on GRANT role; policy quals stored as expression trees, not SQL
  re-parsed under the caller's search path.
- `leakproof` flag on functions/operators (default false for UDFs), consulted
  by the qual-pushdown rule; plan and result cache keys include policy epoch
  and role-set hash.
- Lock manager/SSI victim selection takes a level/tenant comparator;
  read-down uses lock-free snapshot reads.
- Vetted crypto (OpenSSL/BoringSSL, RustCrypto, ring), AEAD only; nonce
  counter persisted before use; keys in `mlock`ed, `MADV_DONTDUMP` memory,
  zeroized on drop; constant-time compares; page format reserves nonce, tag and
  key-version bytes from format version 1.
- Audit as a separate append-only, hash-chained stream outside the user
  transaction, with an external anchoring job; statement-text redaction before
  logging; optional secure-delete that zeroes freed tuples, index entries and
  pages before truncation.

## How to test it

- **Privilege/RLS differential fuzzing**: random roles, grants, policies and
  queries; oracle = same query over materialized authorized views; error codes
  for hidden vs absent objects must match.
- **Leak UDF** in every clause position never sees hidden rows; **revoke model
  check** on random cyclic grant graphs vs a reference; **cache staleness**
  (prepare, revoke, execute; role swap on pooled session).
- **Noninterference harness**: tenant/level A alone vs with adversarial B;
  compare results, aborts and latency distributions.
- **Plaintext canary scan** of every file after spills, checkpoints, crashes,
  backups; **crypto fault injection** (bit flips, page swaps, replay, crash
  between nonce allocation and write).
- **Merkle/VO property tests**: honest proofs verify; any mutation, omission,
  reordering or leaf/internal confusion fails; stale signed roots rejected.
- **Audit tamper tests** (delete/insert/reorder/truncate; aborts keep records);
  **tracker/differencing attacks** on statistical controls; **forensic residue
  test** for deleted canaries within the removal bound; injection corpus
  against protocol and parser.

## Expert review questions

1. Enumerate every code path that opens a relation; which can bypass the
   security context, and what prevents it at compile time?
2. Which revocation semantics do we implement, and what happens to views,
   constraints, cached plans and open cursors on REVOKE CASCADE?
3. Are column privileges checked for predicate-only references?
4. Where are RLS quals injected relative to view expansion, CTE inlining,
   subquery pull-up and pushdown? Which functions are leakproof, and why?
5. What is the plan-cache key and the invalidation path for ALTER POLICY and
   role-membership changes?
6. Can a tenant detect another's rows via unique/FK checks, upserts, lock
   waits, aborts, statistics, EXPLAIN or timing? Who is the SSI/deadlock victim?
7. For every persistent artifact: encrypted under which key, how is (key,
   nonce) uniqueness kept across crashes and non-WAL rewrites, and when is a
   rotated-out key destroyed relative to WAL archives and backups?
8. What is each encrypted column's leakage profile (DET/OPE/RND/HOM) given its
   entropy, and who accepted it?
9. What prevents replay of an old, validly authenticated page or result?
10. Can the DBA read protected data or alter/disable audit undetected? Where is
    the audit anchor held?
11. What is the bounded-removal guarantee for deleted personal data, including
    archives and backups — overwrite or crypto-shredding?
12. For aggregate-only access, what defeats trackers and repeated-query
    averaging?
13. What does pre-authentication code touch, and is it fuzzed?

## Go deeper

- `references/authorization-models-and-enforcement.md` — REVOKE semantics,
  RBAC/SoD, temporal policies, views vs RLS, Truman semantics, masks, purpose.
- `references/mls-and-secure-concurrency-control.md` — BLP, MLS architectures,
  polyinstantiation, inference, covert channels, secure CC/SEP, attack repair;
  also for multi-tenant noninterference.
- `references/encryption-and-key-management-in-engines.md` — TDE, column and
  client-side encryption, keys/rotation, TLS, verifiers, encrypted querying and
  leakage, ORAM, PIR.
- `references/integrity-verification-and-trusted-hardware.md` — hash/MAC/
  signature choice, Merkle proofs, completeness/freshness, untrusted lock
  managers/logs, TPM/SCPU/enclave query processing.
- `references/auditing-intrusion-and-compliance.md` — audit design, tamper
  evidence, forensic residue, IDS/SQL injection, insiders, inference control,
  DP, WORM/erasure, Hippocratic DBMS, secure development lifecycle.
- `references/edbs-entries.md` — all 26 source entries with printed pages.

## Related skills

- `transactions-and-recovery`, `concurrency-control-theory`,
  `recovery-and-durability` — base CC/WAL; here: noninterference, victim rules,
  WAL encryption, log hash chains, malicious-transaction repair.
- `page-and-file-format`, `storage-devices-and-io`, `index-structures-catalog`
  — layout and I/O; here: reserved crypto bytes, AAD, secure zeroing, Merkle
  B+-trees, fossilized indexes, index residue.
- `sql-frontend`, `sql-semantics-and-active-rules`, `query-optimizer`,
  `query-execution-advanced` — binding, views, triggers, rewrites; here:
  privilege checks, definer rights, security barriers, leakproof pushdown,
  trusted-hardware operators.
- `cardinality-and-statistics`, `materialized-views-ivm` — stats and derived
  data as leakage; `dbms-architecture` — reference-monitor placement.
- `distributed-dbms-design`, `replication-protocols`,
  `parallel-database-systems` — inter-node auth/TLS, policy versions in 2PC,
  MLS replicated architectures.
- `temporal-databases` (audit/repair history), `olap-and-warehouse-engines`
  (aggregate inference), `tuning-and-benchmarking` (security overheads).
- `relational-theory` (non-Truman containment), `beyond-relational-engines`, `query-engine-testing`.

## Grounding

EDBS (printed pages): Access Control 9; Auditing and Forensic Analysis 218;
Authentication 224; Data Encryption 750; Database Security 974; Discretionary
Access Control 1140; Hash Functions 1681; Homomorphic Encryption 1720;
Inference Control in Statistical Databases 1916; Intrusion Detection Technology
2031; Mandatory Access Control 2192; Merkle Trees 2231; Message Authentication
Codes 2232; Multilevel Secure DBMS 2349; Privacy-Preserving DBMSs 2822; Private
Information Retrieval 2825; Protection from Insider Threats 2899; Regulatory
Compliance in Data Management 3141; Role-Based Access Control 3252; Secure Data
Outsourcing 3338; Secure Database Development 3346; Secure Transaction
Processing 3358; Storage Security 3760; Symmetric Encryption 3863; Temporal
Access Control 3894; Trusted Hardware 4245.

Seminal: Griffiths & Wade (TODS 1976), Fagin (TODS 1978); Stonebraker & Wong
(1974); Bell & LaPadula (1973/75); Jajodia & Sandhu (SIGMOD 1991); Keefe & Tsai
(S&P 1990); RBAC96 (1996), ANSI INCITS 359-2004; Hippocratic DB (VLDB 2002);
Hacıgümüş et al. (SIGMOD 2002); CryptDB (SOSP 2011); Schneier & Kelsey (TISSEC
1999); Stahlberg et al. (SIGMOD 2007); TrustedDB (SIGMOD 2011). Beyond EDBS:
Naveed et al. (CCS 2015); differential privacy (TCC 2006); EnclaveDB (S&P
2018); PostgreSQL RLS/SCRAM; SQL Server Always Encrypted and ledger tables.
