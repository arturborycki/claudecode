# Text and string indexes: tries, suffix structures, compressed self-indexes, inverted files

Two very different families. **Word-based** indexes (inverted files) treat
text as a sequence of tokens and answer word, phrase, Boolean and ranked
queries. **Full-text (substring) indexes** (suffix trees, suffix arrays,
FM-index, compressed suffix arrays) answer arbitrary substring queries and
are the tool when "words" are not well defined (DNA, logs, code, CJK text).
Tries sit underneath both (vocabularies, dictionaries) and underneath modern
in-memory ordered indexes. Search-engine ranking models and full-text
engines as products belong to `beyond-relational-engines`.

## 1. Tries

A trie stores a set of strings as a rooted tree whose edges are labelled by
symbols; each node represents the prefix spelled from the root; shared
prefixes are stored once. Append a terminator symbol (absent from the
alphabet) so no key is a prefix of another; then keys correspond exactly to
leaves. A trie is a deterministic automaton accepting the key set.

Costs (M = total length of all keys, |x| = query length, sigma = alphabet):

| Operation | Time |
|---|---|
| Build by repeated insertion | O(M) with O(1) branching, O(M log sigma) with ordered child search |
| Membership / prefix test | O(|x|) or O(|x| log sigma) |
| Sorted output | preorder traversal (reverse order: postorder) |
| Prefix enumeration | walk to prefix node, enumerate subtree |

Node representation is the real design decision:

| Child representation | Branching time | Space | Use |
|---|---|---|---|
| Full array of sigma pointers | O(1) | nodes x sigma | small alphabets, top levels |
| Sorted array / list of (symbol, child) | O(log sigma) / O(sigma) | proportional to edges | sparse nodes |
| Balanced BST per node; or first-child/next-sibling binary encoding | O(log sigma) / O(sigma) | edges | general |
| Hash table of edges | O(1) expected | edges + overhead | large alphabets |
| "Deep-shallow": arrays down to depth k, lists below | O(1) near root | balanced | natural language; nodes near the root are dense, deep nodes have one child |

**Compact (path-compressed) trie**: remove unary internal nodes and
concatenate edge labels; every internal node then has >= 2 children, and
node count is O(number of keys) instead of O(M). Store edge labels as
(offset, length) into a key store to keep nodes fixed-size.

**PATRICIA** (Morrison 1968): binary trie over the bit representation of
keys, path-compressed; each internal node stores only the index of the bit
on which it branches (its skip number; bit indexes strictly increase along
any root-to-leaf path, children test later bits than parents). Because skipped bits
are never examined, a search lands on a candidate leaf that must be verified
with one full key comparison. Forgetting that final comparison is the
classic PATRICIA bug. Strength: very long keys, one full comparison per
lookup.

Other uses from the entry: Burstsort (trie-based string sorting), LZ78-style
compression dictionaries, multi-pattern matching automata.

> **Beyond EDBS: ART (Adaptive Radix Tree;** Leis, Kemper & Neumann, ICDE
> 2013). A 256-way radix tree over memcmp-comparable key bytes with four
> adaptive inner-node sizes: Node4 and Node16 (sorted key bytes + child
> pointers; Node16 searched with one SIMD compare), Node48 (a 256-entry byte
> array indexing into 48 child slots), Node256 (direct array). Nodes grow
> and shrink between types. Path compression stores a node's common prefix in
> the node (pessimistic: full prefix; optimistic: length only, verified at the
> leaf); lazy expansion keeps single-key subtrees as a leaf. Height depends on
> key length, not N; no rebalancing; ordered iteration and range scans come
> free. Requires binary-comparable key encoding (see btree-engineering.md,
> normalized keys). Synchronisation: optimistic lock coupling and ROWEX
> (Leis et al., DaMoN 2016). Used by HyPer and DuckDB for in-memory indexes.

> **Beyond EDBS:** Masstree (Mao, Kohler & Morris, EuroSys 2012) is a trie
> of B+-trees, each layer indexing an 8-byte key slice; HOT (Binna et al.,
> SIGMOD 2018) is a height-optimised trie with high, data-adaptive fan-out.
> Both target in-memory OLTP with long or variable keys.

## 2. Suffix trees

The suffix tree of y[0..n-1] (terminated by a unique symbol) is the compact
trie of its n suffixes:

* n leaves (one per suffix), every internal node branching >= 2, so <= n-1
  internal nodes and O(n) edges;
* edge labels stored as (start, length) into y, so O(n) words of space but
  y must be resident;
* each internal node is a substring that occurs at least twice (a repeat).

Queries, pattern x of length p:

| Query | Method | Time |
|---|---|---|
| is x a substring | spell x from the root | O(p) (times branching cost) |
| longest prefix of x occurring in y | same walk, stop at mismatch | O(p) |
| count occurrences | number of leaves below the locus (store counts) | O(p) |
| locate all | enumerate leaves below the locus | O(p + occ) |
| first/last occurrence | min/max leaf label below the locus (store them) | O(p) |

Construction:

| Algorithm | Property |
|---|---|
| Weiner 1973 | first linear-time algorithm; needs O(n sigma) space |
| McCreight 1976 | linear time and space; inserts suffixes longest-first using **suffix links** (node for a.v links to node for v) to jump to the next insertion point |
| Ukkonen 1995 | online, left-to-right over y, also suffix-link based |
| Farach 1997 | linear time for integer alphabets [1..n^c] (no log sigma factor) |

With O(n) space child lookup costs O(log min(n, sigma)) per step. Related
automata: the suffix automaton/DAWG (minimised suffix trie, linear size;
Blumer et al. 1985), the compact DAWG (Crochemore & Verin 1997). Generalised
suffix trees index a set of strings (terminate each with a distinct symbol).

Engineering reality: even carefully engineered (Kurtz 1999) a suffix tree
takes roughly 10-20 times the text size, and its pointer chasing is hostile
to caches and disks. For a DBMS it is mainly a design reference; suffix
arrays or FM-indexes are what you ship.

## 3. Suffix arrays

SA[0..n-1] lists suffix start positions in lexicographic order; optional
LCP[i] = length of the longest common prefix of suffixes SA[i-1] and SA[i]
(Manber & Myers 1993).

* Space: n integers (4n bytes with 32-bit positions) plus the text; LCP
  another n integers or a compressed form.
* All occurrences of x form one contiguous SA interval [sp, ep].
  - Plain binary search: O(p log n) symbol comparisons.
  - With LCP-based bounds (Manber-Myers LCP-LR arrays): O(p + log n).
  - With sampled suffixes (suffix trays): O(p + log sigma).
* count = ep - sp + 1; locate = SA[sp..ep].
* Construction: prefix doubling O(n log n) (Manber-Myers); linear time
  DC3/skew (Kärkkäinen & Sanders 2003), Kim et al. 2003, Ko & Aluru 2003,
  SA-IS induced sorting (Nong, Zhang & Chan 2009, the practical default).
  LCP in linear time from SA and its inverse (Kasai et al. 2001).
* Dictionary indexing: concatenate dictionary strings with separator '#'
  into S_D; prefix search for P = substring search for "#P"; suffix search
  = "P#"; substring search directly.

Suffix arrays are simple, cache-friendlier than suffix trees, and easy to
store on disk as a sorted file; locate is a range scan.

## 4. Compressed self-indexes (FM-index, CSA)

Goal: space close to the k-th order empirical entropy nH_k(T), while
supporting count(P), locate(P) and extract(i, j) **without storing T**
(the index replaces the text: a self-index).

### Burrows-Wheeler transform

Append $ (smallest symbol). Sort all rotations of T$; L = last column.
Equivalently L[i] = T[SA[i] - 1] (with T[-1] = $). Example T = banana:

```
sorted rotations     SA   L
$banana               6   a
a$banan               5   n
ana$ban               3   n
anana$b               1   b
banana$               0   $
na$bana               4   a
nana$ba               2   a          L = "annb$aa"
```

Symbols preceding equal contexts cluster in L, which is why L compresses
well. **LF mapping**: the j-th occurrence of symbol c in L corresponds to the
j-th occurrence of c in the first column F; LF(i) = C[c] + rank_c(L, i),
where C[c] = number of symbols in T$ smaller than c and rank_c(L, i) = number
of c in L[0..i-1]. LF steps backward through the text.

### Backward search (count)

```
count(P[0..p-1]):
  c = P[p-1]; sp = C[c]; ep = C[c+1] - 1
  for i = p-2 downto 0:
      c  = P[i]
      sp = C[c] + rank_c(L, sp)
      ep = C[c] + rank_c(L, ep + 1) - 1
      if sp > ep: return 0
  return ep - sp + 1
```

2p rank queries; on the example, "ana" narrows to rows [1,3] -> [5,6] ->
[2,3], count 2, SA[2..3] = {3, 1}.

### Locate and extract

SA is not stored. Sample SA at every eta-th text position (e.g.
eta = log^(1+eps) n); to locate row i, apply LF until a sampled row is hit
after t steps: pos = sample + t. extract(i, j) walks LF from the nearest
sampled position after j. Sampling costs O((n log n)/eta) bits.

### Rank structures

All FM-index engineering is "how to answer rank_c on a compressed L":
block L, store cumulative counts per symbol at block starts, and count
within the block by decoding it (better compression) or with a wavelet
tree (faster, log sigma bit-rank steps). Theoretical best: rank in O(1) in
nH_k(T) + o(n) bits for polylog alphabets (Ferragina, Manzini, Mäkinen &
Navarro 2007).

### Compressed suffix arrays (Grossi & Vitter 2005; Sadakane)

Use Psi(i) = SA^-1[SA[i] + 1] (inverse of LF). Grossi-Vitter recursively
halve SA: a bitvector marks even entries, Psi values are kept for odd ones,
and the even entries divided by 2 form the next level; log log n levels.
Psi is increasing within runs of suffixes sharing a first symbol, so it
gap-encodes well. Sadakane replaced the text by a bitvector marking where the
first symbol changes, giving O(p) suffix comparisons and an nH_0 Psi
encoding; his practical CSA combines Psi with backward search and sampling.

### Others

LZ-index (Navarro; LZ78 parsing plus tries over phrases): weaker theory,
fast in practice. Compressed suffix trees (Sadakane 2007): CSA plus about
6n + o(n) bits of succinct tree topology; all suffix-tree operations with at
most O(log n) slowdown.

### Practical numbers (Pizza&Chili benchmark, as reported in EDBS)

Compressed indexes take roughly 40-80% of the original text, count about
20,000-50,000 20-symbol patterns per second, locate about 10^5 occurrences
per second, extract about 1 MB/s; one (count) to three (locate) orders of
magnitude slower than a plain suffix array, while up to ~18x smaller.
Locate is the weak spot: non-local memory access per LF step. Libraries:
SDSL-lite.

External memory: String B-tree (Ferragina & Grossi 1999) is the classical
disk-aware substring index (uncompressed); compressed cache-oblivious string
B-trees exist for dictionaries.

## 5. Inverted files: structure

* **Vocabulary (lexicon):** distinct terms after normalisation (case
  folding, stemming, stop-word removal), each with document frequency, IDF,
  posting-list length and the file offset of its list. Grows sublinearly
  (Heaps' law), usually fits in memory. Organisation: hash for O(1) exact
  lookup; sorted array/B-tree or a front-coded trie when prefix/wildcard
  queries are needed.
* **Postings:** per term, a list of
  - doc ids (Boolean), or
  - (doc id, tf) / (doc id, precomputed impact) (ranking), or
  - (doc id, tf, positions...) (phrase and proximity).
  Keep doc ids, frequencies and positions in separate streams so queries
  that do not need positions never read them.
* **Ordering:** doc-id order enables gap compression and merge-based
  intersection; impact/frequency order (Persin, Zobel & Sacks-Davis 1996)
  lets ranked queries read only list prefixes but breaks doc-id gaps (gaps
  still work within runs of equal tf, which are long at the tail because of
  Zipf).

## 6. Query processing

| Query | Method |
|---|---|
| single term | read list |
| AND | intersect lists, shortest first; probe longer lists with skips or galloping (exponential) search |
| OR | k-way merge (heap) |
| phrase | intersect doc ids, then check adjacent positions; a next-word index (term -> next-term postings) accelerates common phrases; indexing all word pairs explodes the vocabulary |
| ranked, term-at-a-time (TAAT) | process one list fully into an accumulator table; memory proportional to candidate docs |
| ranked, document-at-a-time (DAAT) | advance all list cursors in doc-id order; per-document score complete at once; needs doc-ordered lists |

Dynamic pruning for top-k: MaxScore (Turtle & Flood 1995) and WAND (Broder
et al. 2003) skip documents whose upper-bound score cannot enter the heap;
Block-Max indexes (Ding & Suel 2011) store the max score per fixed block so
whole blocks are skipped; treap-encoded lists (Konow et al. 2013) are binary
search trees on doc id and heaps on score, pruning subtrees below threshold.
Static pruning removes postings unlikely to matter at build time (lossy).

**Skips:** gap coding forces sequential decoding; insert absolute values
(doc id + byte offset) every s postings so a search can jump to the right
block and decode only that block. Moffat & Zobel (1996) suggest s around
sqrt(list length) for one level; block codecs make the block itself the
skip unit. Very frequent terms are cheaper as plain bitvectors over doc ids,
intersected with AND (Moffat & Culpepper 2007).

Caching layers: posting-list cache, result cache, and an intersection
("projection") cache of frequent term pairs (Long & Suel 2005).

## 7. Construction

Main-memory inversion fails once postings exceed RAM. Sort-based
construction (Witten, Moffat & Bell):

```
pass A (optional): parse all docs, build vocabulary -> perfect hash term ids, stop/typo filtering
pass B: parse again, emit (term id, doc id, tf [, positions]) into buffer
        when buffer full: sort by (term id, doc id), write run
pass C: multiway merge of runs into final lists, compressing as you go,
        writing the lexicon with offsets
```

The two-pass form removes the vocabulary from memory during inversion
(term ids are perfect-hashed). Single-pass in-memory inversion (SPIMI;
Heinz & Zobel 2003) builds per-run dictionaries on the fly and merges runs,
avoiding the extra parse.

Distribution: **document partitioning** (each node indexes a subset of
documents; queries broadcast; results merged) is the simple and dominant
choice; **term partitioning** (each node owns some terms' full lists) cuts
per-query fan-out but concentrates load and complicates updates.

Maintenance strategies (from the entry): rebuild; intermittent merge (an
in-memory delta index merged with the on-disk index at query time and
periodically folded in); incremental in-place update of each list (like
variable-length record management, with growth slack).

> **Beyond EDBS:** Geometric partitioning (Lester, Moffat & Zobel 2005)
> keeps a logarithmic number of sub-indexes of geometrically increasing size
> and merges them like an LSM tree, bounding both merge cost and the number
> of partitions a query touches. Lucene's immutable segments plus a tiered
> merge policy are the production form of the same idea (see lsm-storage).

## 8. Posting-list compression

Lists of increasing integers are stored as gaps (d-gaps): 3, 8, 9, 20 ->
3, 5, 1, 11. Long lists have small gaps; Zipf makes a few very long lists
hold most postings, so gap coding pays.

Codes (x >= 1, N = floor(log2 x)):

| Code | Encoding | Bits | Example x = 9 (1001) |
|---|---|---|---|
| Unary | x-1 ones then a zero | x | 111111110 |
| Elias gamma | N zeros, then x in binary (N+1 bits) | 2N + 1 | 000 1001 |
| Elias delta | gamma(N+1), then low N bits of x | N + 2 floor(log2(N+1)) + 1 | 00100 001 |
| Golomb(b) / Rice(r, b = 2^r) | quotient floor((x-1)/b) in unary, remainder in binary (truncated binary for Golomb) | about log2 b + x/b | Rice r = 2: q = 2 -> 110, rem 00 |
| Variable-byte | 7 payload bits per byte, one flag bit marks continuation/termination | 8 ceil((N+1)/7) | 1 byte |
| Simple9 / Simple16 (Anh & Moffat) | 32-bit word: 4-bit selector + 28 payload bits split into equal fields (28x1, 14x2, 9x3, 7x4, 5x5, 4x7, 3x9, 2x14, 1x28) | word-aligned | packs with neighbours |
| PForDelta (Zukowski et al. 2006) | block of e.g. 128: choose b so ~90% fit in b bits, bit-pack all, patch exceptions separately | ~b per value + exceptions | block-level |

For gaps that behave geometrically (term in each doc with probability q),
Golomb with b ~ 0.69 x mean gap is near optimal; choose b per list. Rice
codes are Golomb with power-of-two b, decodable with shifts.

Bit-aligned codes (gamma, delta, Golomb/Rice) are the most compact;
byte/word-aligned and block codes decode 10-20x faster (per the entry),
and since decode speed now dominates, block codecs are the default.
Reported sizes: positional indexes about 40% of the text (about 20% with
stop words removed); non-positional 10-20%; well-compressed document-level
indexes can reach about 10% of the text, and compression usually speeds
queries by reducing I/O.

> **Beyond EDBS:** SIMD bit-packing and decoders (Lemire & Boytsov 2015,
> "Decoding billions of integers per second through vectorization"; Stream
> VByte, Lemire, Kurz & Rupp 2018) decode billions of integers per second.
> Elias-Fano (quasi-succinct indexes, Vigna WSDM 2013) stores a monotone
> sequence of n values below U in about n(2 + log2(U/n)) bits with O(1)
> random access and fast NextGEQ (native skipping); partitioned Elias-Fano
> (Ottaviano & Venturini, SIGIR 2014) improves it further. These are the
> state-of-the-art codecs for in-memory posting lists. Lucene encodes
> doc-id blocks with fixed-width bit packing plus multi-level skip data.

## 9. Choosing a text index

| Need | Choose | Why |
|---|---|---|
| word / Boolean / ranked search on natural-language text | inverted file | smallest, fastest, locality-friendly; everything else is compared against it |
| substring / regex-prefix search, no tokenisation | suffix array (or FM-index if space-bound) | contiguous SA interval per pattern |
| substring search with text compressed below original size | FM-index / CSA | self-index; slower locate |
| dictionary of strings, prefix/suffix/substring lookups | trie / front-coded sorted array / FM-index over concatenation | |
| in-memory ordered index on binary keys | ART / B+-tree | see btree-engineering.md |
| very cheap filtering, append-heavy, rarely queried | signature file / Bloom per block | see bloom-filters.md; inverted files usually still win (Zobel, Moffat & Ramamohanarao 1998) |

## 10. Pitfalls and tests

* Tokeniser/normaliser drift between index time and query time silently
  drops matches. Version the analyzer with the index.
* Doc-id reassignment after deletes breaks gap streams; use tombstone
  bitmaps and rewrite during merge.
* Positions across field boundaries create false phrase matches; insert a
  position gap between fields/values.
* Skip entries must store both the doc id and the byte (and bit) offset; an
  off-by-one in either skips a posting.
* Suffix-array search with a pattern that is a prefix of the last suffix,
  empty patterns, and patterns containing the terminator.
* FM-index: C[] must include $; rank boundaries are half-open; test
  count(P) against naive substring counting on random small alphabets.
* Tests: round-trip every codec on random lists including gap 1 runs,
  maximal values, empty lists and single elements; compare intersection
  results of compressed lists with set intersection; compare all
  query types with a brute-force scan over the documents.

Sources: EDBS "Trie" (p.4225), "Suffix Tree" (p.3839), "Indexing Compressed
Text" (p.1861), "Inverted Files" (p.2037), "Text Index Compression" (p.4075),
"Index Creation and File Structures" (p.1842), "Signature Files" (p.3491).
