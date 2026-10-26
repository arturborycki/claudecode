# Encryption, key management, authentication, and querying encrypted data

Scope: the cryptographic primitives an engine uses and how to use them
correctly; at-rest encryption (page/file vs column/cell) and its interaction
with the buffer pool, WAL, indexes, compression, temp files, backups and
replication; key hierarchies and rotation; in-transit protection; client and
inter-node authentication; computing on encrypted data (bucketization,
deterministic/order-preserving encryption, homomorphic encryption, CryptDB
onions, searchable encryption), its leakage, and access-pattern protection
(ORAM, PIR). Integrity primitives (hashes, MACs, Merkle trees) are in
`integrity-verification-and-trusted-hardware.md`.

---

## 1. Primitives, restated for engine builders

### 1.1 Symmetric ciphers and modes

- Block cipher `E: {0,1}^ℓ × {0,1}^n → {0,1}^n` with `D_k(E_k(x)) = x`.
  DES (n=64, ℓ=56) is broken by exhaustive search; 3DES = `E_k1(D_k2(E_k3(x)))`
  is legacy (64-bit block ⇒ birthday problems after ~2^32 blocks). AES (Rijndael,
  FIPS 197, 2001): n=128, ℓ ∈ {128,192,256}. Use AES.
- Stream ciphers XOR a keystream into the plaintext; **the same keystream must
  never be used twice** — two ciphertexts under the same (key, nonce) XOR to
  the XOR of plaintexts. RC4 (named in EDBS) is now considered broken; do not
  use it.
- Modes:

| Mode | Property | Engine use | Pitfall |
|---|---|---|---|
| ECB | Deterministic per block; equal blocks ⇒ equal ciphertext | Never for data | Reveals structure (repeated tuples, zero padding in pages) |
| CBC | Chained; random IV per message | Legacy column/file encryption | IV must be unpredictable; padding-oracle attacks if errors distinguish bad padding |
| CTR | Keystream from (nonce, counter); random access, parallel | Page encryption with unique per-write nonce | Nonce reuse = keystream reuse; malleable (bit flips pass through) |
| XTS (IEEE 1619) | Tweakable, length-preserving, per-sector tweak | Volume/file/page encryption where no space for IV/tag exists | Deterministic per (key, tweak): rewriting the same page with same content is visible; no integrity |
| GCM (AEAD) | CTR + polynomial MAC; confidentiality + integrity | Page, WAL record, cell encryption when you can store a 12-byte nonce and 16-byte tag | Catastrophic on nonce reuse (keystream reuse + forgery key recovery) |

> **Beyond EDBS:** EDBS covers only confidentiality modes. Production
> practice is authenticated encryption (AEAD: AES-GCM, ChaCha20-Poly1305,
> AES-GCM-SIV for nonce-misuse resistance). Encryption without integrity lets a
> storage-level attacker flip bits in a page and have the engine trust them.

### 1.2 Public-key and hybrid encryption

RSA: `N = pq`, public `(N, e)`, private `d` with `ed ≡ 1 (mod φ(N))`;
`c = x^e mod N`. Textbook RSA is deterministic and malleable; real use needs
randomized padding (OAEP). Public-key ops are orders of magnitude slower than
AES, so engines use **hybrid** encryption: a random symmetric data key
encrypts the data, and the data key is encrypted (wrapped) under a public or
master key. Authenticity of public keys comes from a PKI (certificate
authorities).

### 1.3 Attack models (what "secure" must mean)

Ciphertext-only < known-plaintext < chosen-plaintext (CPA) < chosen-ciphertext
(CCA). An engine is a chosen-plaintext oracle by construction (users insert
rows that get encrypted), so any at-rest scheme must be CPA-secure
(randomized). Deterministic and order-preserving schemes are, by design, not
CPA-secure; their leakage must be accepted explicitly (§5).

---

## 2. At-rest encryption inside the engine

### 2.1 Where to encrypt

```
 client ── TLS ──> [ parser / executor ] ── tuples in plaintext in memory
                         │
                  [ buffer pool: plaintext pages ]
   page/file TDE ───────>│<── encrypt on write-out / decrypt on read-in
                  [ storage manager / OS / disk ]  -- ciphertext pages, WAL, temp, backups
 column/cell enc:  value encrypted inside the tuple (executor or client decrypts)
 client-side enc:  value encrypted before it reaches the server (Always-Encrypted style)
```

| Granularity | Protects against | Doesn't protect against | Query impact | Index impact |
|---|---|---|---|---|
| Disk / volume (SED, dm-crypt) | Stolen disks | Anyone with OS access on the running host, backups copied as files | None | None |
| Tablespace / file / page (TDE) | Stolen files, backups, storage admins, cloud storage provider | DBA, anyone with SQL access, memory dumps | Decrypt cost per page miss only | None: indexes are pages too |
| Column / cell (server-side keys) | Above + users/tools that read storage via unprivileged paths; selective protection | DBA with key access; memory | Decrypt per value accessed; predicates on ciphertext need DET/OPE or decrypt-then-filter | Index on ciphertext supports only what the scheme preserves (equality for DET); index on plaintext must itself be encrypted |
| Client-side (keys never on server) | Server, DBA, cloud operator | Client compromise; leakage of DET/OPE/access patterns | Server can only evaluate what the encryption preserves; rest pushed to client | As column-level, but server can never build plaintext indexes |

Rule of thumb: page-level TDE is the default for "encryption at rest" because
it is transparent to the optimizer, indexes, compression and the executor; use
column-level only where a separate key domain is required (different
custodian, per-tenant/per-subject keys for crypto-shredding).

### 2.2 Page-level TDE design

- **Boundary**: encrypt in the storage manager's write path (after the page is
  final, after checksum computation or with the AEAD tag replacing the
  checksum), decrypt in the read path before the page enters the buffer pool.
  The buffer pool, executor and optimizer stay unchanged.
- **What must be covered** (each is a classic omission): data files, index
  files, WAL/redo log, undo/rollback segments, temp files and sort/hash spill
  files, materialized intermediate results, FSM/visibility maps if they reveal
  data, backups and archived logs, replication/log-shipping streams, crash
  dumps and core files, and the plaintext buffer pool if it is ever swapped
  (lock it or encrypt swap).
- **Nonce/IV uniqueness**: for CTR/GCM, derive the nonce from
  `(page number, LSN or write counter)`. Invariant: *a page image is never
  written twice under the same (key, nonce) with different content.* Engines
  that modify pages without advancing the LSN (hint bits, checksum-only
  rewrites, in-place flag updates on eviction) break LSN-derived nonces; either
  bump a per-page write counter stored in cleartext header bytes, or use XTS
  and accept its deterministic leakage.
- **Space for metadata**: AEAD needs nonce + tag per page (≈28 bytes) and a key
  version id. Reserve it in the page header/trailer format from day one
  (format versioning: `page-and-file-format`). Retrofitting changes usable
  page size and breaks tuple/index fan-out assumptions.
- **What stays in cleartext**: page header fields needed before decryption
  (page number, LSN, key version) — they must not leak data. Authenticate them
  as associated data so they cannot be swapped.
- **Integrity**: with AEAD, tag verification failure is a corruption or
  tampering signal; treat like a checksum failure but log as a security event.
  Bind the page number and file id into the associated data so an attacker
  cannot replay page A into slot B. Replay of an *older version of the same
  page* is not caught by per-page tags — that needs a freshness mechanism (a
  Merkle tree over pages or a trusted LSN high-water mark).
- **Cost**: AES-NI/ARMv8 crypto make AES-GCM/XTS a few GB/s per core; cost is
  paid per physical I/O, not per tuple, so it is usually small compared to I/O
  latency but visible on fully cached scans of cold data and on WAL-heavy
  workloads (WAL encryption sits on the commit path; encrypt per WAL block, not
  per record, to amortize).

### 2.3 Column / cell encryption design

- **Randomized vs deterministic**: randomized (CPA-secure, per-value IV)
  forbids server-side equality, grouping and joins on the column;
  deterministic allows them but leaks equality and frequency.
- **Indexing an encrypted column**: (a) index over deterministic ciphertext →
  equality lookups only, range scans impossible; (b) index over plaintext →
  the index pages must be encrypted too (page TDE), otherwise the index leaks
  the column; (c) index over OPE ciphertext → ranges, with OPE leakage.
  Oracle TDE column encryption requires the column be encrypted without salt
  (deterministic) to be indexed — a concrete instance of (a).
- **Compression**: ciphertext is incompressible. Compress *then* encrypt.
  Columnar engines must encrypt after dictionary/RLE encoding, i.e. at
  page/segment level; encrypting each value first destroys dictionary
  compression (except with DET, which preserves equality and so dictionary
  encoding — and its frequency leakage). Compression ratio is a length side
  channel (cf. CRIME/BREACH for TLS); usually acceptable at page granularity,
  not for attacker-influenced small records mixed with secrets.
- **Predicate evaluation**: decrypt-then-filter in the executor requires keys
  in the server; vectorize decryption (decrypt a whole column chunk) and push
  the predicate after decryption; never let the optimizer push a predicate on
  the ciphertext representation unless the scheme preserves it.
- **Statistics**: histograms and MCV lists on an encrypted column are
  plaintext copies of the data distribution. Either compute stats only over
  ciphertext (useless for ranges) or protect the statistics catalog with the
  same key domain.

> **Beyond EDBS:** SQL Server Always Encrypted (2016) is the mainstream
> client-side design: a column master key held outside the server wraps column
> encryption keys stored in the catalog; the driver encrypts parameters and
> decrypts results; columns are deterministic (equality, joins, grouping,
> indexing) or randomized (no server-side operations). The 2019 "secure
> enclaves" variant lets the server evaluate richer predicates inside an
> enclave (see trusted hardware reference).

### 2.4 Key management

Hierarchy (envelope encryption):
```
  KMS / HSM: master key (KEK, never leaves HSM)
        └── wraps ──> database/tablespace/tenant keys (DEKs), stored wrapped in catalog/file header
                         └── encrypt ──> pages / WAL blocks / cells   (optionally per-object subkeys via HKDF)
```
- **Rotation of the KEK**: re-wrap DEKs only — O(number of keys), online.
- **Rotation of a DEK**: re-encrypt data. Do it online: store a key-version id
  per page/segment; a background re-encryptor rewrites pages under the new
  version through the normal write path (WAL-logged, crash-safe); readers pick
  the key by version. Old DEK is destroyed only after the last page, all WAL
  segments, backups and replicas using it are gone — track a low-water mark.
- **Crypto-shredding**: destroying a key makes all data under it unreadable,
  including copies in WAL archives and backups. Per-tenant or per-data-subject
  keys turn "delete everywhere" into "delete one key" — the practical answer to
  right-to-erasure versus immutable logs/backups (see compliance reference).
  EDBS records the idea as encrypting data and overwriting the decryption key
  to remove data from files and backups simultaneously.
- **Loss of key = loss of data**: key backup/escrow is part of the durability
  story; test restore with key rotation in between.
- **Key in memory**: keep unwrapped DEKs in locked, non-dumpable memory; zero
  on release; never write keys or passphrases to logs (statement logging of
  `ALTER ... KEY`/`PASSWORD` statements is a recurring leak).
- **Periodic re-encryption** (also recommended in the Storage Security entry)
  limits exposure of any single key and of long-term ciphertext to future
  cryptanalysis.

### 2.5 In transit

- Client↔server: TLS with server certificate verification; optionally client
  certificates. Refuse plaintext fallback in production; protect against
  downgrade (e.g. an attacker stripping a STARTTLS-style upgrade).
- Inter-node (MPP exchanges, replication, log shipping, 2PC): mutual TLS or an
  AEAD channel keyed per node pair; authenticate *every* node — an
  unauthenticated replica join or exchange endpoint is full data access. EDBS
  (Storage Security) notes that traffic inside the firewall is often left
  unencrypted; zero-trust practice no longer accepts that.
- Storage networks: zoning, port binding, LUN masking restrict which hosts can
  address which volumes; they are access control, not confidentiality.

---

## 3. Authentication in the engine

Entity authentication: something known (password, PIN, key), something held
(token, smart card), something inherent (biometric); combine factors.
Data-origin authentication: MAC (shared key) or digital signature (no shared
key).

Password verifier storage and checks:
- Store `salt, params, H_slow(salt, password)`; never plaintext or unsalted
  fast hashes. Salt defeats precomputed tables and multi-user batch guessing;
  iteration ("slow hash") raises per-guess cost.
- Lockout after N failures limits online guessing but enables account-DoS;
  prefer exponential backoff per (account, source).
- Rules and aging: length/charset rules shrink the space if over-specified;
  forced frequent changes produce predictable passwords.
- One-time passwords: Lamport/S/Key hash chain — server stores `h^{t-i}(k)`,
  accepts `y` iff `h(y)` equals the stored value, then stores `y`.
- Challenge-response avoids replay: server sends a fresh random challenge; the
  client proves knowledge of the secret without sending it.
- Network auth services: Kerberos, X.509/PKI, single sign-on.

> **Beyond EDBS:** PostgreSQL's SCRAM-SHA-256 (v10+) is a salted, iterated
> challenge-response mechanism with optional TLS channel binding; the server
> stores only verifiers, so a stolen `pg_authid` does not let an attacker log
> in without an offline guessing attack. Modern password hashing functions are
> memory-hard (scrypt, Argon2 — winner of the 2015 Password Hashing
> Competition); PBKDF2 and bcrypt remain common.

Engine invariants:
1. No catalog or data access before authentication completes (pre-auth code
   paths are the attack surface; keep them minimal and fuzzed).
2. Uniform failure: same error and similar timing for "no such user" and "wrong
   password" (prevents user enumeration); constant-time verifier comparison.
3. Credentials never logged, never in error messages, never in
   `pg_stat_activity`-like views (`CREATE USER ... PASSWORD '...'` must be
   redacted before statement logging).
4. Session identity is immutable except through audited `SET ROLE`/`SET
   SESSION AUTHORIZATION` paths; connection poolers that multiplex users must
   reset all session state (role, GUCs, temp objects, prepared statements).
5. Inter-node and replication logins are authenticated like users and have
   least privilege (a replication role should not be able to run DML).

---

## 4. Querying encrypted data — the design space

Setting: database-as-a-service. Data owner encrypts; an untrusted
("honest-but-curious") server stores ciphertext and evaluates as much of the
query as possible; a trusted client/proxy rewrites queries and post-processes.

| Technique | Server can evaluate | Leakage to server | Overhead / limits |
|---|---|---|---|
| Bucketization (Hacıgümüş, Iyer, Li, Mehrotra, SIGMOD 2002) | Equality/range on bucket ids; joins on bucket ids | Bucket membership, approximate distribution | Superset results → client-side filtering; bucket design trades precision vs leakage (equi-depth leaks less than equi-width) |
| Privacy homomorphisms for aggregates (Hacıgümüş et al., DASFAA 2004; Rivest, Adleman, Dertouzos 1978) | SUM/COUNT on encrypted attributes | Depends on PH; early PHs were insecure | Arithmetic expansion of ciphertexts |
| Deterministic encryption (DET) | Equality selection, equi-join, GROUP BY, DISTINCT, equality index | Equality pattern and frequencies | None beyond encryption |
| Order-preserving encryption (OPES: Agrawal, Kiernan, Srikant, Xu, SIGMOD 2004) | Range, ORDER BY, MIN/MAX, range index, sort-merge join | Total order; with OPES, approximate distribution flattened to a target | Exact range answers (no superset); vulnerable to inference with auxiliary data |
| Additive HE (Paillier) | SUM, AVG (with COUNT), linear combinations | None (CPA-secure) | Ciphertext 2× modulus (e.g. 4096 bits for 2048-bit n); ~ms per op |
| Multiplicative HE (RSA, ElGamal) | Products | RSA textbook is deterministic | Rarely useful in SQL |
| XOR-homomorphic (Goldwasser–Micali) | XOR of bits | None | Bitwise, very expensive |
| Fully homomorphic (Gentry 2009; van Dijk et al. 2010 over integers) | Any circuit | None | Many orders of magnitude slower; no data-dependent control flow (every query is a full scan / oblivious circuit) |
| Searchable symmetric encryption (Song, Wagner, Perrig, IEEE S&P 2000; Goh secure indexes 2003; Chang & Mitzenmacher 2004) | Keyword match on encrypted text | Search and access pattern; with indexes, document-keyword incidence once queried | Linear scan (Song) or per-document Bloom-filter index (Goh); conjunctive search (Golle, Staddon, Waters 2004); comparison/subset predicates in public-key setting (Boneh & Waters 2007) |
| Attribute-based encryption (Sahai & Waters 2005; KP-ABE Goyal et al. 2006; CP-ABE Bethencourt et al. 2007) | Nothing; enforces access policy cryptographically at decryption | Policy structure | Key management for policy changes (revocation requires re-encryption) |

When data is split across several mutually distrusting owners rather than
outsourced to one server, the alternative is secure multiparty computation
(Yao's two-party protocol, 1982; generalized to many parties by Goldreich,
Micali, Wigderson, 1987): parties jointly evaluate a function revealing only
its output. Generic SMC is far too slow for SQL; practical systems use
task-specific protocols, often built on additive HE as below (EDBS entry
"Secure Multiparty Computation Methods", seen only as a fragment here).

### 4.1 Homomorphic properties (the algebra you rely on)

```
RSA:      E(x1)·E(x2) = (x1·x2)^e            = E(x1·x2 mod n)
ElGamal:  (g^r1, x1·h^r1)·(g^r2, x2·h^r2)    = E(x1·x2 mod p)
GM:       r1² y^b1 · r2² y^b2 = (r1 r2)² y^(b1+b2) = E(b1 ⊕ b2)
Paillier: (g^x1 r1^n)(g^x2 r2^n) mod n²      = E(x1 + x2 mod n);  E(x)^k = E(k·x)
```
SUM over a column under Paillier is a modular product of ciphertexts — an
aggregate the server can compute without keys, implementable as a
user-defined aggregate whose state is a bignum mod n². AVG = SUM/COUNT with
COUNT in plaintext. No comparison, so no `WHERE amount > 100` on the HOM
column.

### 4.2 CryptDB onions (Popa, Redfield, Zeldovich, Balakrishnan, SOSP 2011)

Each column is stored as several "onions", layers of encryption with the
strongest outermost:
```
Eq onion:   RND( DET( JOIN(value) ) )      -> equality, then cross-column equi-join
Ord onion:  RND( OPE( OPE-JOIN(value) ) )  -> range / ORDER BY
Search:     SEARCH(value)                  -> keyword LIKE on text
Add:        HOM(value)                     -> SUM (Paillier)
```
A trusted proxy rewrites each query. When a query needs a capability (e.g.
equality on column c), the proxy sends the layer key to a server UDF that
**peels** the outer layer of that column (`UPDATE t SET c_eq = DECRYPT_RND(key,
c_eq)`); the layer stays peeled. Security therefore *ratchets down* to the
weakest scheme ever required by the workload. Relational Cloud (Curino et al.,
CIDR 2011) builds DBaaS transactions on top of CryptDB; transactional semantics
are inherited from the underlying engine.

> **Beyond EDBS:** Naveed, Kamara & Wright (CCS 2015) recovered large
> fractions of plaintext from DET and OPE columns of realistic medical data
> using only frequency analysis and sorting against public auxiliary data —
> deterministic and order-preserving columns of low-entropy attributes
> (gender, age, diagnosis codes, ZIP) should be treated as effectively
> plaintext. Provably secure OPE in the random-order-preserving-function
> sense (Boldyreva et al., Eurocrypt 2009) still leaks order, and the same
> authors' follow-up (Crypto 2011) showed it also leaks roughly the upper half
> of each plaintext's bits; mutable OPE (Popa et al.,
> S&P 2013) reaches IND-OCPA but needs an interactive index; order-revealing
> encryption has its own leakage-abuse attacks (Grubbs et al., S&P 2017).
> Even CPA-secure schemes leak **access patterns** and **result volumes**;
> Kellaris et al. (CCS 2016) give generic reconstruction attacks from range
> query volumes alone.

### 4.3 Choosing a scheme per column (design rule)

1. Classify columns by required server-side operations and by entropy.
2. High-entropy identifiers (UUIDs, account numbers): DET is acceptable.
3. Low-entropy attributes: RND only; push predicates to the client or a trusted
   enclave; or accept the leakage explicitly in the threat model.
4. Numeric measures aggregated server-side: HOM (Paillier) column alongside RND.
5. Ranges: prefer bucketization with coarse buckets + client filtering, or
   enclave evaluation, over OPE on sensitive data.
6. Record which onion layers are peeled; alert when a workload change peels a
   sensitive column.

---

## 5. Access-pattern privacy: ORAM and PIR

Encryption hides values, not *which* records are touched. Observing accesses
to an encrypted e-mail repository let an attacker infer most queries (Islam,
Kuzu, Kantarcioglu, NDSS 2012).

- **ORAM** (Goldreich & Ostrovsky, JACM 1996): the client continuously
  reshuffles and re-encrypts blocks and mixes real accesses with dummies, so
  the physical access sequence is independent of the logical one. Lower bound
  Ω(log N) blocks per access. > **Beyond EDBS:** Path ORAM (Stefanov et al.,
  CCS 2013) is the practical baseline: a binary tree of buckets, each block
  mapped to a random leaf; an access reads and rewrites one root-to-leaf path
  (O(log N) blocks) plus a client stash. Oblivious query operators (ObliDB,
  Opaque's oblivious mode) apply the same idea to sort, join and aggregate.
- **PIR**: retrieve item i of an n-item database without revealing i.
  - Single-server *information-theoretic* PIR needs Ω(n) communication (Chor,
    Goldreich, Kushilevitz, Sudan, FOCS 1995); multi-server IT-PIR with
    non-colluding replicas achieves sublinear communication.
  - Computational single-server PIR: Kushilevitz & Ostrovsky (FOCS 1997,
    quadratic residuosity, database as a √n×√n bit matrix, user sends √n
    numbers of which one is a non-residue); Cachin, Micali, Stadler (Eurocrypt
    1999, Φ-hiding, polylog communication); Gentry & Ramzan (ICALP 2005,
    O(log² n) private block retrieval via CRT); constructions from
    homomorphic encryption (Ostrovsky & Skeith 2007; FHE-based, Yi et al.
    TKDE 2013).
  - Formal shape: QueryGen(n, i, 1^k) → (Q, s); Response(DB, Q) → R;
    Retrieve(R, s) → b_i; security = no PPT server distinguishes queries for i
    and j with non-negligible advantage.
  - Practicality: computational PIR must touch every record per query (else
    untouched records reveal they are not i), so server cost is Ω(n); Sion &
    Carbunar (NDSS 2007) argued single-server cPIR was then slower than
    downloading the whole database. Trusted-hardware PIR moves the oblivious
    scan into a secure coprocessor.
  - PIR protects only the client; when the server's data is also valuable,
    combine with oblivious transfer (e.g. the location-query protocol in the
    PIR entry: OT for the cell key, then PIR for the encrypted cell).
- Private stream search (Ostrovsky & Skeith, Crypto 2005): a server filters a
  stream against secret encrypted keywords and accumulates matches in an
  encrypted buffer; collisions in buffer slots lose matches, so buffer size
  must be chosen so each match survives with high probability.

---

## 6. Failure modes

| Failure | Consequence | Test / guard |
|---|---|---|
| Nonce reuse after crash (counter not persisted before use) | Keystream reuse across two page images | Crash-injection test that rewrites pages; assert unique (key, nonce) via a debug-mode nonce ledger |
| WAL, temp, spill or backup left unencrypted | "Encrypted" database readable from archive | Grep-for-plaintext test: insert canary strings, scan every file the engine writes (including after crashes and during sort spills) |
| Key or passphrase in logs/core dumps | Total compromise | Log scanner in CI; `madvise(DONTDUMP)`/`mlock` key pages |
| DET on low-entropy column | Plaintext recoverable by frequency analysis | Data-classification review; entropy estimate per DET column |
| Statistics on encrypted column stored in clear | Distribution leak | Catalog review; stats under same key domain |
| Encrypt-then-compress | Compression ratio ≈ 1 | Benchmark guard |
| Unauthenticated encryption | Bit-flip tampering undetected | Use AEAD; fault-injection test flips ciphertext bits, expects verification failure |
| Page relocation / replay | Old or swapped page accepted | Bind page id in AAD; freshness via Merkle root or trusted LSN watermark |
| Key rotation drops old key too early | Unreadable old WAL/backups | Restore-from-old-backup test after rotation |
| Onion peeled by an ad-hoc query | Permanent leakage increase | Alert on layer changes |

---

Sources: Data Encryption (p.750); Symmetric Encryption (p.3863); Homomorphic
Encryption (p.1720); Authentication (p.224); Storage Security (p.3760); Secure
Data Outsourcing (p.3338); Private Information Retrieval (p.2825); Secure
Transaction Processing (p.3358) for CryptDB/Relational Cloud; Regulatory
Compliance in Data Management (p.3141) for HE cost; Auditing and Forensic
Analysis (p.218) for deletion by key destruction.
