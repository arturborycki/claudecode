# EDBS entries in the database-security-internals bundle

Pull any full entry with the `edbs-reference` skill:
`python3 <edbs-reference>/scripts/edbs.py show "<Entry>"`.

| Entry | Printed page | What it gives an engine builder |
|---|---|---|
| Access Control | p.9 | The (subject, object, privilege) model, subject/object/privilege hierarchies, the reference monitor's required properties (non-bypassable, tamper-proof), DAC vs MAC vs RBAC framing; catalog storage of authorizations |
| Auditing and Forensic Analysis | p.218 | What an audit log must record (incl. aborted transactions), native audit vs triggers vs WAL vs transaction-time DBs, protecting the log, forensic residue (DB slack, FS slack, indexes, WAL, temp), forensic-transparency desiderata, deletion by overwrite or key destruction |
| Authentication | p.224 | Password verifier storage (salt, slow hash, lockout), one-time passwords (S/Key hash chain), challenge-response, data-origin authentication via MACs/signatures, Merkle trees for partial verification |
| Data Encryption | p.750 | Symmetric vs public-key, stream vs block ciphers, DES/3DES/AES, ECB/CBC/CFB/OFB/CTR modes, RSA and hybrid encryption, attack models (COA/KPA/CPA/CCA) |
| Database Security | p.974 | Security properties (secrecy, integrity, availability, authenticity, completeness) mapped to DBMS mechanisms; why a DBMS needs its own security beyond the OS; SQL injection as the dominant web-era threat |
| Discretionary Access Control | p.1140 | SQL GRANT/REVOKE, grant option, cascading revocation and multiple-grantor subtleties, view privileges, DAC's Trojan-horse/copy weakness, open vs closed policies |
| Hash Functions | p.1681 | Preimage, second-preimage, collision resistance; MD5/SHA-1 deprecation, SHA-2, SHA-3 |
| Homomorphic Encryption | p.1720 | Homomorphic identities of RSA, ElGamal, Goldwasser–Micali, Paillier; first FHE schemes — the algebra behind encrypted aggregation |
| Inference Control in Statistical Databases | p.1916 | Tabular (dominance and p% rules, suppression, rounding, CTA), queryable DBs (perturbation, query restriction, camouflage, tracker attack), microdata masking; risk–utility trade-off |
| Intrusion Detection Technology | p.2031 | IDS architecture, attack taxonomy, anomaly (static/dynamic) vs misuse detection, DB-specific IDS references (RBAC-profile detection, query floods), IDS self-protection |
| Mandatory Access Control | p.2192 | Bell–LaPadula simple-security and ★ properties, DBMS restriction to write-at-own-level, noninterference vs lock-based covert channels, Trusted Database Interpretation |
| Merkle Trees | p.2231 | Construction and verification of hash trees; verifying a subset with sibling hashes against one signed root |
| Message Authentication Codes | p.2232 | Keyed integrity/authenticity, difference from signatures, HMAC and CBC-MAC constructions |
| Multilevel Secure Database Management System | p.2349 | History and architectures of MLS/DBMSs (integrity lock, trusted subject, kernelized/SeaView, LOCK Data Views, distributed), hard problems: inference (undecidable in general), aggregation, secure transaction processing, polyinstantiation vs signaling channels |
| Privacy-Preserving DBMSs | p.2822 | Hippocratic database ten principles and strawman architecture (privacy metadata, purpose-based attribute/record access control, query intrusion detector, retention manager) |
| Private Information Retrieval | p.2825 | IT vs computational PIR, Kushilevitz–Ostrovsky, Cachin–Micali–Stadler, Gentry–Ramzan constructions, formal security game, PIR+OT for protected location data, private stream search |
| Protection from Insider Threats | p.2899 | CERT definition and taxonomy of malicious insiders (sabotage, IP theft, fraud) — motivates DBA/auditor separation and insider-resistant audit |
| Regulatory Compliance in Data Management | p.3141 | Retention minima/maxima, audits, confidentiality mandates; WORM and soft-WORM storage, trusted hardware limits, compliance storage, fossilized indexes, secure deletion and history independence |
| Role-Based Access Control | p.3252 | RBAC0–3 (sessions, hierarchies, constraints), SoD variants, NIST/ANSI INCITS levels, ARBAC/SARBAC administration, temporal/spatial extensions, RBAC encoding DAC/MAC |
| Secure Data Outsourcing | p.3338 | Requirements (query privacy, authenticity, integrity, completeness, confidentiality w.r.t. provider and users), PIR/ORAM, Merkle-tree and aggregate-signature result verification, boundary-tuple completeness, bucketization, OPE, searchable encryption, ABE |
| Secure Database Development | p.3346 | Building a general-purpose secure DBMS vs a secure application with a DB; pattern- and UMLsec-based lifecycles; query modification vs views as enforcement choices; OS/DBMS/application-server security layering |
| Secure Transaction Processing | p.3358 | Covert channels via 2PL and TO, secure CC (validation, multiversion TO, two-snapshot), replicated-architecture protocols and poset anomalies, multilevel transactions and atomicity, secure early prepare, real-time secure CC, damage assessment/repair, transactions over encrypted cloud data (Blind Stone Tablet, CloudLock, CryptDB), policy consistency in 2PC |
| Storage Security | p.3760 | Storage-level authentication, on-wire and on-disk encryption, key retention and re-encryption, corruption detection vs correction (CRC/hash/ECC), zoning, LUN masking, CAS, WORM |
| Symmetric Encryption | p.3863 | Stream vs block ciphers, DES/AES block sizes, modes of operation (short companion to Data Encryption) |
| Temporal Access Control | p.3894 | TAM periodicity constraints and WHENEVER/ASLONGAS/UPON derivation rules, TDAM object-time formulas, TRBAC role enabling and triggers, GTRBAC duration/cardinality/activation constraints and conflict resolution |
| Trusted Hardware | p.4245 | FIPS 140-2 levels, TPM (passive) vs secure coprocessors (IBM 4758/4764/4765), tamper response, order-of-magnitude performance penalty |

Notes on the bundle: the Access Control entry is followed by part of "Access
Control Administration Policies" (SA / owner / joint administration,
delegation via GRANT OPTION and ADMIN OPTION, why grantor and timestamp are
stored for recursive revocation); its tail was recovered in a supplement and is
folded into `authorization-models-and-enforcement.md` §2.2. Other recovered
tails (for Database Security, Multilevel Secure DBMS, Merkle Trees, Secure
Database Development) turned out to be fragments of neighbouring entries —
Database Techniques to Improve Scientific Simulations, Multilevel Transactions
and Object-Model Transactions, Message Queuing Systems, Secure Multiparty
Computation Methods — and added nothing to the security entries except a
one-paragraph SMC pointer in the encryption reference. Other neighbour
fragments in the main bundle (ARIES/multilevel recovery, Information
Extraction) were ignored.
