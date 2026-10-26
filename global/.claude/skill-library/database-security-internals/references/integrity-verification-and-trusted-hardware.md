# Integrity verification, authenticated data structures, and trusted hardware

Scope: cryptographic hash functions and MACs as engine primitives;
signatures; Merkle hash trees and authenticated index structures; verifying
authenticity, integrity, completeness and freshness of query results from an
untrusted server (outsourced databases); integrity of storage itself; secure
coprocessors, TPMs and enclaves as a trusted computing base for query
processing; untrusted servers in transaction protocols (locking and
durability outsourced to an adversary).

---

## 1. Hashes and MACs as engine primitives

### 1.1 Properties

Cryptographic hash `h: {0,1}* → {0,1}^m`:
1. **Preimage resistance** (one-way): given y, infeasible to find x with h(x)=y.
2. **Second-preimage resistance**: given x, infeasible to find x' ≠ x with
   h(x') = h(x).
3. **Collision resistance**: infeasible to find any x ≠ x' with h(x) = h(x').
   Strongest; implies (2), and for compressing functions practically implies (1).
Generic collision cost is 2^(m/2) (birthday), so a 256-bit output gives
128-bit collision security.

Status: MD5 broken (practical collisions); SHA-1 deprecated (practical
collisions demonstrated in 2017 — beyond EDBS, which notes only reduced-round
attacks); SHA-2 (SHA-224/256/384/512, FIPS 180) current; SHA-3 (Keccak, FIPS
202, 2015) a structurally different alternative.

### 1.2 Checksums vs hashes vs MACs vs signatures

| Primitive | Detects | Adversary model | Engine use |
|---|---|---|---|
| CRC32C / xxHash / Fletcher | Random corruption (bit rot, torn writes) | None — trivially forgeable | Page checksums, WAL record checksums, network frames |
| Error-correcting code (Reed–Solomon, erasure codes) | Detect *and* correct random errors | None | Storage layer, RAID, object stores |
| Cryptographic hash | Any change, *if the digest is stored somewhere the adversary cannot modify* | Adversary cannot change the reference digest | Content addressing (CAS), dedup, Merkle leaves, audit chains anchored externally |
| MAC (HMAC, CMAC/CBC-MAC, GCM tag) | Any change by anyone without the key | Shared-key; verifier = signer | Page/WAL authentication, inter-node messages, audit-log entries, session cookies/tokens |
| Digital signature | Any change; public verifiability, non-repudiation | Signer holds private key; anyone verifies | Signed Merkle roots, outsourced data, notarized audit anchors, signed backups |

Rules:
- A plain hash stored next to the data protects only against accidents. An
  attacker who can modify the data can recompute the hash. Integrity against
  adversaries needs a key (MAC) or a trusted anchor (signature, external
  notary, TPM/enclave-held value).
- Build MACs as HMAC (Krawczyk, Bellare, Canetti, RFC 2104), not `h(k || m)`:
  Merkle–Damgård hashes (MD5, SHA-1, SHA-2) allow length extension of
  `h(k||m)`.
- Compare MAC tags in constant time.
- MAC keys and encryption keys are distinct (derive both from a master with a
  KDF, labelled by purpose).
- Hash-then-sign: signatures are computed over a digest for efficiency; the
  digest function's collision resistance is then part of the signature's
  security.

---

## 2. Merkle hash trees

### 2.1 Construction (Merkle 1979)

Leaves `L_i = h(m_i)`; internal node `N = h(N_left || N_right)`; root digest
`R` authenticates the whole set; sign `R` once.

```
                 R = h(H12 || H34)            <- signed
               /                 \
     H12 = h(H1||H2)       H34 = h(H3||H4)
       /       \              /       \
   H1=h(m1)  H2=h(m2)    H3=h(m3)  H4=h(m4)
```
Proof (verification object, VO) for `m1`: `{H2, H34}`; verifier computes
`h(h(h(m1)||H2) || H34)` and compares to the signed root. Proof size and
verification time: O(log n) hashes per item; for k adjacent items in a sorted
tree: O(k + log n).

Engineering details that matter:
- **Domain separation**: hash leaves and internal nodes with different
  prefixes, e.g. `h(0x00 || leaf)` and `h(0x01 || left || right)` (as in RFC
  6962 certificate-transparency logs). Without it, an internal node's
  concatenated children can be presented as a leaf value (second-preimage
  style forgery).
- **Unbalanced trees**: define precisely how an odd node is promoted; ad-hoc
  duplication of the last node has caused forgery bugs in deployed systems.
- **Canonical encoding** of tuples before hashing (lengths, types, NULLs,
  collation-independent bytes); two encodings of the same tuple must not hash
  differently, and two different tuples must not share an encoding.
- **Update cost**: changing one leaf rewrites O(log n) internal digests up to
  the root, and the root must be re-signed (or re-MACed) — the root becomes a
  serialization point; batch updates per epoch.

### 2.2 Authenticated index structures

- Merkle tree per relation over tuples in key order (Devanbu, Gertz, Martel,
  Stubblebine, DBSec 2000): the server returns the result plus the hashes
  needed to recompute the root.
- **Merkle B+-tree** (each B+-tree node stores child digests; node digest =
  hash over its entries and child digests). > **Beyond EDBS:** Li,
  Hadjieleftheriou, Kollios, Reyzin (SIGMOD 2006) studied such dynamic
  authenticated index structures for outsourced databases (MB-tree); the fan-out
  is lower than a plain B+-tree because each entry carries a digest, and every
  update rewrites the root-to-leaf path's digests.
- XML / hierarchical: hash each node over its content, attributes and child
  digests bottom-up; the document root digest authenticates the document
  (Bertino, Carminati, Ferrari et al., TKDE 2004; Devanbu et al., CCS 2001).

---

## 3. Verifying outsourced query results

Requirements (from the Secure Data Outsourcing and Database Security entries):

| Property | Meaning | Mechanism |
|---|---|---|
| Authenticity | Results originate from the owner | Signature on Merkle root, or per-tuple signatures |
| Integrity | Results unmodified | Same |
| Completeness | Nothing that satisfies the query was omitted | Boundary tuples + sorted Merkle tree, or signature chains |
| Freshness | Results reflect the latest version, not a replayed old state | Versioned/timestamped signed roots, epoch certificates, or a trusted monotonic counter |
| Confidentiality | Server and unauthorized users cannot read data | Encryption (see encryption reference) |
| Access privacy | Server cannot learn what was queried | PIR/ORAM |

### 3.1 Completeness for range queries via boundary tuples

For a range query `a ∈ [lo, hi]` over a Merkle tree built on tuples sorted by
`a`, the server returns the result tuples plus the **immediate predecessor of
lo and immediate successor of hi** (or sentinel −∞/+∞ leaves) and the VO. The
verifier checks:
1. root recomputes and the signature verifies (authenticity, integrity);
2. predecessor.a < lo and successor.a > hi;
3. returned tuples plus boundaries are *contiguous leaves* (VO positions are
   consecutive) — therefore no tuple was skipped.
Cost: O(k + log n) hashes. Weakness: the two boundary tuples disclose data
outside the result.

### 3.2 Signature aggregation and chaining

- Per-tuple signatures with **aggregate signatures** (Boneh, Gentry, Lynn,
  Shacham, Eurocrypt 2003; applied by Mykletun, Narasimha, Tsudik, NDSS 2004):
  the server multiplies the signatures of all result tuples into one; one
  verification checks them all. Communication O(1) signature for any result
  size; does not by itself prove completeness.
- **Signature chaining** (Narasimha & Tsudik, DASFAA 2006): each tuple's signed
  message includes the hash of its immediate predecessor in each sort order
  supported; returned boundary tuples plus aggregated chain signatures prove
  contiguity. Cost: one chain per sortable attribute.
- Pang, Jain, Ramamritham, Tan (SIGMOD 2005) prove completeness without
  revealing the boundary tuples' values, by signing digests derived from
  attribute values so that the boundaries can be shown to lie outside the range
  without exposing them.

### 3.3 Freshness

Signatures prove only that data *was* valid at some point. Replay of a stale
but correctly signed state is the default attack once updates exist.
- Include an epoch/version in the signed root and publish (or let clients
  fetch from the owner) the current epoch; clients reject older epochs.
- Bound staleness with periodically re-signed roots carrying a timestamp
  ("valid until"), at the cost of re-signing even when nothing changes.
- Verifiable freshness for multi-version key-value stores (Tang et al., ICDE
  2014) fits this pattern for big-data stores.
- > **Beyond EDBS:** for multi-client settings without online owner, the best
  achievable guarantee is *fork consistency* (SUNDR, Li, Krohn, Mazières,
  Shasha, OSDI 2004): a server can partition clients into forks but cannot
  later join them without detection. Transparency logs (RFC 6962) add gossip of
  signed tree heads to detect forks.

### 3.4 Engine-level integrity without outsourcing

The same tools defend a self-hosted engine against storage-level tampering
(a compromised storage server, SAN admin, or cloud block store):
- AEAD per page (confidentiality + per-page integrity) catches modification;
- a Merkle tree over page MACs (or over segment files, as in authenticated
  file systems) anchored by a root kept in a trusted place (TPM NV counter,
  enclave, or signed and stored remotely) catches *rollback* of individual
  pages to older valid images;
- WAL records chained by hash (each record includes the previous record's
  digest) make log truncation or splicing detectable — the same construction
  as tamper-evident audit logs.

---

## 4. Untrusted servers inside transaction protocols

- **Blind Stone Tablet** (Williams, Sion, Shasha, NDSS 2009): clients keep
  local databases; the untrusted server only stores a client-encrypted,
  authenticated log and orders transactions. Lock-based variant: a global lock
  serializes; the client catches up, executes, appends an encrypted, signed
  update; each client also verifies other clients' **signed hash chains** over
  applied transactions, so the server cannot reorder or drop updates
  undetected. Wait-free variant: optimistic pre-commit messages, server returns
  earlier pre-commits, client checks conflicts locally and publishes
  commit/abort.
- **CloudLock** (Tan, Liu, Wu, IEEE CLOUD 2011): the cloud server runs the lock
  manager and could lie ("lock busy") to reorder work; the protocol attaches a
  history of recent lock grants and uses an independent time server and an
  owner-side lock ledger (requested/granted/released times) to detect
  violations.
- **Encrypted transactional stores** (Biswas & Vidyasankar 2013): clients
  execute optimistically on local copies, send read/write *sets* (no values) for
  server-side conflict detection, then ship a log encrypted under a key shared
  among clients.
- **Verifiable computation** in general (Gennaro, Gentry, Parno, Crypto 2010) is
  orders of magnitude too expensive for general SQL; specialized query
  authentication (CorrectDB, Bajaj & Sion, VLDB 2013, using trusted hardware)
  narrows the gap.

Engine lesson: when the component that orders operations (lock manager,
sequencer, log) is untrusted, make its decisions *verifiable* — signed,
hash-chained, and checkable by participants — rather than trying to make it
honest.

---

## 5. Trusted hardware

### 5.1 Device classes

| Class | Examples | Capability | Limits |
|---|---|---|---|
| TPM (Trusted Computing Group) | Discrete or firmware TPM 1.2/2.0 | Key storage, sealed storage bound to platform measurements, monotonic counters, attestation of boot state | Passive: cannot run application code or report on running applications; slow |
| HSM / secure coprocessor (SCPU) | IBM 4758 (486-class), 4764 (PowerPC, Linux), 4765 PCIe; FIPS 140-2 Level 4 certified | General-purpose programmable CPU in a tamper-responding enclosure; zeroizes state on physical attack (battery-backed); CCA crypto API | About an order of magnitude slower than host CPUs (heat dissipation limits gate density in the enclosure); little memory; PCIe round trips |
| CPU enclaves | Intel SGX, AMD SEV-SNP / Intel TDX (VM-level), ARM TrustZone/CCA | Run code on the main CPU with memory encrypted/integrity-protected; remote attestation | Side channels; limited enclave page cache (SGX1); trust in vendor microcode/attestation |

(Enclaves are beyond EDBS; the entry predates their use in databases.)

### 5.2 Database designs using trusted hardware

- **TrustedDB** (Bajaj & Sion, SIGMOD 2011): an SCPU-hosted query processor
  handles operations over sensitive attributes while the host processes public
  attributes; the planner splits queries and costs the cross-boundary
  transfers. Key lesson stated in EDBS: running everything inside the SCPU fails
  on performance; protocols must touch trusted hardware sparsely and
  asynchronously from the main data flow.
- **CorrectDB** (Bajaj & Sion, VLDB 2013): the SCPU verifies query execution
  (authenticated data structures + trusted verification), giving practical
  query authentication.
- **Compliance storage**: trusted hardware at the storage site enforces WORM
  and retention against insiders with physical access (see compliance
  reference).
- **PIR with trusted hardware** (Iliev & Smith 2005; Wang et al., ESORICS
  2006): the SCPU performs the oblivious scan/shuffle so the host learns
  nothing about which record was requested.
- > **Beyond EDBS:** Cipherbase (Arasu et al., CIDR 2013) puts a small
  trusted expression evaluator (FPGA) beside SQL Server's executor; only
  expression evaluation over encrypted values runs inside. SQL Server Always
  Encrypted with secure enclaves (2019) adopts the same split with VBS/SGX
  enclaves. EnclaveDB (Priebe, Vaswani, Costa, IEEE S&P 2018) keeps tables,
  indexes and precompiled stored procedures of an in-memory engine inside an
  SGX enclave and adds integrity and freshness protection for its log, which
  lives outside the enclave. Opaque (Zheng et al., NSDI 2017) runs Spark SQL operators in
  enclaves with an oblivious mode that pads and sorts to hide access patterns.
  Enclaves are vulnerable to controlled-channel (page-fault), cache and
  speculative-execution side channels; without oblivious algorithms, an
  enclave join or index lookup leaks its access pattern to the host OS.

### 5.3 Design rules for a trusted-hardware split

1. Minimize the trusted computing base: put the *decision* (comparison,
   decryption, verification) in the trusted component, not the data movement.
2. Batch crossings; cost them in the optimizer (`query-execution-advanced` /
   cost model) as a separate operator with high per-call latency.
3. Assume the host observes every crossing: what is passed (sizes, counts,
   order) is leakage unless padded/oblivious.
4. Rollback protection: the trusted component must hold a monotonic counter or
   root digest so the host cannot restart it on an older sealed state.
5. Attestation: the client must verify *what code* runs in the enclave/SCPU
   before provisioning keys.

---

## 6. Tests

- Merkle: property test — for random sets and random queries, every honest VO
  verifies; every single-bit mutation of result, VO, boundary, or root fails;
  omitting any one in-range tuple fails; reordering leaves fails; leaf/internal
  confusion (present an internal node as a leaf) fails.
- Freshness: replay an older signed root after an update; client must reject.
- Page integrity: flip bits, swap two pages, restore an older copy of one page;
  expect detection respectively by tag, by AAD binding, by root/counter.
- Hash-chained log: delete, insert, reorder, and truncate records; each must be
  detected at the next verification against the external anchor.
- Trusted split: trace all host↔trusted crossings for two inputs with equal
  public shape but different secrets; traces must match (for oblivious mode).

---

Sources: Hash Functions (p.1681); Message Authentication Codes (p.2232);
Merkle Trees (p.2231); Authentication (p.224); Secure Data Outsourcing
(p.3338); Database Security (p.974); Trusted Hardware (p.4245); Regulatory
Compliance in Data Management (p.3141); Secure Transaction Processing
(p.3358); Storage Security (p.3760); Private Information Retrieval (p.2825).
