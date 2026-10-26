---
name: edbs-reference
description: "Use when a database-internals question needs authoritative depth beyond what a library skill states: pulling the full Encyclopedia of Database Systems (EDBS, 2nd ed.) entry on a concept, finding which of the 1,414 entries cover a topic, following cross-references between entries, or citing the canonical papers behind an algorithm. Triggers on EDBS, encyclopedia, 'look it up', 'what does the literature say', canonical definition, seminal paper, recommended reading, cross-reference, survey of approaches, history of a technique, 'is there a standard name for this'. Apply even when phrased as 'go deeper on X' or 'are we missing a known approach', and before inventing a new algorithm for a classic problem."
---

# EDBS reference shelf

The Encyclopedia of Database Systems, 2nd ed. (Liu & Özsu, eds., Springer
2018) has 1,414 entries written by the people who
invented or surveyed each technique. The library skills distil roughly 560 of
them into operating knowledge. This skill gives you the *rest of the depth*:
an index of every entry (title, pages, cross-references, which library skill
it fed) and a script that pulls an entry's full text from the user's own PDF.

## When to reach for it
- A library skill names an entry under **Grounding** and you need the details
  (proof sketch, variant, parameter, history) that the skill summarised.
- You are about to design something "new" for a classic problem. Search first;
  most classic problems already have a named family of solutions with known trade-offs.
- You need the canonical paper list for a design doc or code comment. Each
  entry ends with *Recommended Reading*.
- You are mapping unfamiliar territory: walk the cross-reference graph.

## Commands
```bash
S=<this-skill-dir>/scripts/edbs.py          # stdlib Python 3.8+
python3 $S where                            # which PDF will be used
python3 $S search write skew snapshot       # rank entry titles
python3 $S show "Serializable Snapshot Isolation"
python3 $S show "Linear Hashing" --section Foundations
python3 $S sections "Multilevel Recovery and the ARIES Algorithm"
python3 $S show "Two-Phase Commit" --section "Recommended Reading"
python3 $S show "Index Join" --extra 1           # entry looks cut off: read one more page
python3 $S show "Solid State Drive (SSD)" --raw   # pages untrimmed (2-column interleaving)
python3 $S related "Snapshot Isolation"     # xrefs out + entries pointing in
python3 $S skill concurrency-control-theory # entries a skill was built from
```
PDF resolution: `--pdf`, then `$EDBS_PDF`, then common folders (`./docs`,
`~/books`, `~/Documents`, `~/Downloads`, …). If it's not found, ask the user
for the path and set `EDBS_PDF`. Needs `pdftotext` (poppler) or `pypdf`.
Extracted text is cached in `~/.cache/edbs/`.

Without the PDF, `search`, `related` and `skill` still work from
`references/index.tsv`. Use them to name the right concept and its neighbours,
then reason from the matching library skill.

## Research protocol (use this order)
1. **Library skill first.** It holds the engineering distillation (invariants,
   trade-offs, tests). Its `references/edbs-entries.md` lists its source entries.
2. **`show` the entry** for the specific gap. Prefer `--section Foundations`
   (or *Scientific Fundamentals* / *Key Points*), which is where the mechanism lives.
3. **`related`** to find sibling techniques and the competing approaches.
4. **Recommended Reading** of the entry gives the primary papers. Name them
   (author, year, venue) in design docs. Don't invent citations.
5. **Check currency.** Entries date from 2009–2018. For anything about current
   systems (PostgreSQL, DuckDB, Spanner, Iceberg, …), check the current docs
   or source; the encyclopedia gives the concept, not today's implementation.

## Citing
In design docs and code comments, cite as: `EDBS 2e, "<Entry>", p.<printed page>`.
The printed page is the number on the page, which differs from the PDF page
index. Both are in `index.tsv`.

## Copyright etiquette
The book is the user's licensed copy. Read entries freely to reason. When
writing into the repo (docs, comments, skills), **paraphrase and cite**. Don't
paste entry text into files. A short quoted definition with a citation is fine.

## Entry → skill map (where the distilled version lives)
| Library skill | EDBS areas it draws on |
|---|---|
| `dbms-architecture` | DBMS architectures, buffer management, memory hierarchy, main-memory DBMS |
| `storage-devices-and-io` | storage structures & systems, advanced storage, I/O model |
| `relational-theory` | relational theory, logics & databases, dependencies, incomplete information |
| `query-execution-advanced` | query processing, ranking queries, approximate & adaptive processing |
| `cardinality-and-statistics` | query optimization, synopses/sketches, histograms, sampling |
| `materialized-views-ivm` | views & view management |
| `concurrency-control-theory` | transaction management, extended transaction models |
| `recovery-and-durability` | logging/recovery, backup, disaster recovery |
| `index-structures-catalog` | indexing, text indexing, bitmap/hash/tree structures |
| `multidimensional-and-similarity-indexing` | spatial/multidimensional, temporal indexing, similarity search |
| `parallel-database-systems` | parallel database systems, big-data platforms |
| `distributed-dbms-design` | distributed database systems, cloud, multitenancy |
| `replication-protocols` | data replication, consistency models |
| `olap-and-warehouse-engines` | data warehouse, OLAP, column stores, array DBs |
| `stream-processing-engines` | stream data management, complex event processing |
| `temporal-databases` | temporal databases |
| `sql-semantics-and-active-rules` | query languages, active databases |
| `tuning-and-benchmarking` | self-management, tuning & performance, benchmarks |
| `beyond-relational-engines` | NoSQL, XML, graph/RDF, uncertain data, provenance |
| `database-security-internals` | database security & privacy |

The other ~850 entries (IR models, data mining, visualisation, health
informatics, GIS applications, web services, …) have no distilled skill but
are fully searchable here.

## Files
- `scripts/edbs.py`: the CLI above.
- `references/index.tsv`: `title, pdf_first, pdf_last, printed_page, skills, xrefs` for all 1,414 entries.
