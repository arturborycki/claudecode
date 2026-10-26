#!/usr/bin/env python3
"""edbs.py — navigate the Encyclopedia of Database Systems (2nd ed., Springer 2018)
from your own licensed PDF copy.

Commands
  search  <words...>        rank entry titles by match (title words, then xrefs)
  show    "<Entry Title>"   print the full text of one entry, pulled from the PDF
          [--section NAME]  only that section (Definition, Foundations, Key Points,
                            Historical Background, Key Applications, Future Directions,
                            Cross-References, Recommended Reading, ...)
          [--max-chars N]   truncate output (default 60000)
  related "<Entry Title>"   cross-references out of, and into, an entry
  skill   <skill-name>      entries a library skill was distilled from
          [--extra N]       also read N following pages (entry continues past its range)
          [--raw]           whole pages, untrimmed (for entries that share a page
                            with a neighbour and get interleaved in 2-column order)
  sections "<Entry Title>"  list the section headings present in an entry
  where                     show which PDF file will be used

PDF location (first hit wins): --pdf PATH, $EDBS_PDF, then common locations
(./, ./docs, ./books, ~/books, ~/Documents, ~/Downloads, ~/Desktop) for a file
whose name contains "Encyclopedia" and "Database".

Text extraction uses `pdftotext` (poppler) when present, else the `pypdf`
package. Extracted entries are cached in ~/.cache/edbs/.
Standard library only otherwise. Python 3.8+.
"""
import argparse, csv, glob, os, re, shutil, signal, subprocess, sys

if hasattr(signal, "SIGPIPE"):
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # play nicely with `| head`

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, "..", "references", "index.tsv")
CACHE = os.path.expanduser("~/.cache/edbs")
SECTIONS = ["Synonyms", "Definition", "Historical Background", "Foundations",
            "Scientific Fundamentals", "Key Points", "Key Applications",
            "Future Directions", "Experimental Results", "Data Sets",
            "URL to Code", "Cross-References", "Recommended Reading"]


def load_index():
    rows = []
    with open(INDEX, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            r["pdf_first"] = int(r["pdf_first"]); r["pdf_last"] = int(r["pdf_last"])
            r["skills"] = [s for s in r["skills"].split(",") if s]
            r["xrefs"] = [s.strip() for s in r["xrefs"].split(";") if s.strip()]
            rows.append(r)
    return rows


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def resolve(rows, title):
    t = norm(title)
    exact = [r for r in rows if norm(r["title"]) == t]
    if exact:
        return exact[0]
    hits = rank(rows, title)
    if hits and hits[0][0] > 0:
        return hits[0][1]
    sys.exit(f"No entry matches {title!r}. Try: edbs.py search {title}")


def rank(rows, query):
    q = set(norm(query).split())
    if not q:
        return []
    out = []
    for r in rows:
        tw = set(norm(r["title"]).split())
        score = 3 * len(q & tw) + (2 if norm(query) in norm(r["title"]) else 0)
        score += 0.5 * sum(1 for x in r["xrefs"] if q & set(norm(x).split()))
        if score:
            out.append((score - 0.01 * len(tw), r))
    out.sort(key=lambda x: -x[0])
    return out


def find_pdf(explicit=None):
    cands = [explicit, os.environ.get("EDBS_PDF")]
    for c in cands:
        if c and os.path.isfile(os.path.expanduser(c)):
            return os.path.expanduser(c)
    dirs = [".", "docs", "books", "~/books", "~/Books", "~/Documents",
            "~/Downloads", "~/Desktop"]
    for d in dirs:
        for p in glob.glob(os.path.join(os.path.expanduser(d), "**", "*.pdf"), recursive=True):
            b = os.path.basename(p).lower()
            if "encyclopedia" in b and "database" in b:
                return p
    return None


def extract_pages(pdf, first, last):
    if shutil.which("pdftotext"):
        res = subprocess.run(["pdftotext", "-f", str(first), "-l", str(last), pdf, "-"],
                             capture_output=True, text=True, check=True)
        return res.stdout
    try:
        import pypdf  # type: ignore
    except ImportError:
        sys.exit("Need poppler's `pdftotext` or `pip install pypdf` to read the PDF.")
    rd = pypdf.PdfReader(pdf)
    return "\n".join(rd.pages[i].extract_text() or "" for i in range(first - 1, last))


def trim(text, title, next_titles):
    def start_of(t, s):
        # tolerate glyphs the PDF renders differently (e.g. "B+-Tree" -> "BC-Tree")
        pat = "".join(re.escape(c) if c.isalnum() or c == " " else ".{0,2}" for c in t)
        for m in re.finditer(pat + r"\s*\n", s):
            if re.search(r"\n?(Synonyms|Definition)\n", s[m.end():m.end() + 700]):
                return m.start()
        return None
    st = start_of(title, text)
    if st is not None:
        text = text[st:]
    cuts = [c for c in (start_of(t, text[200:]) for t in next_titles) if c is not None]
    if cuts:
        text = text[:200 + min(cuts)]
    text = text.replace("\f", "\n")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # de-hyphenate line breaks
    return text.strip()


def entry_text(rows, r, pdf):
    os.makedirs(CACHE, exist_ok=True)
    key = os.path.join(CACHE, re.sub(r"[^A-Za-z0-9]+", "_", r["title"])[:120] + ".txt")
    if os.path.exists(key) and not r.get("_nocache"):
        return open(key, encoding="utf-8").read()
    i = next(k for k, x in enumerate(rows) if x["title"] == r["title"])
    nxt = [x["title"] for x in rows[i + 1:i + 6]]  # neighbours can interleave in 2-column order
    txt = trim(extract_pages(pdf, r["pdf_first"], r["pdf_last"]), r["title"], nxt)
    if not r.get("_nocache"):
        with open(key, "w", encoding="utf-8") as f:
            f.write(txt)
    return txt


def split_sections(txt):
    pat = r"\n(" + "|".join(re.escape(s) for s in SECTIONS) + r")\n"
    parts = re.split(pat, "\n" + txt)
    out = {"_head": parts[0]}
    for h, body in zip(parts[1::2], parts[2::2]):
        out[h] = out.get(h, "") + body
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["search", "show", "related", "skill", "sections", "where"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--pdf")
    ap.add_argument("--section")
    ap.add_argument("--raw", action="store_true")
    ap.add_argument("--extra", type=int, default=0)
    ap.add_argument("--max-chars", type=int, default=60000)
    ap.add_argument("-n", type=int, default=15)
    a = ap.parse_args()
    rows = load_index()
    q = " ".join(a.args)

    if a.cmd == "where":
        print(find_pdf(a.pdf) or "PDF not found — set EDBS_PDF=/path/to/edbs.pdf")
        return
    if a.cmd == "search":
        for s, r in rank(rows, q)[:a.n]:
            sk = (" [" + ", ".join(r["skills"]) + "]") if r["skills"] else ""
            print(f"{r['title']}  — p.{r['printed_page']}{sk}")
        return
    if a.cmd == "skill":
        for r in rows:
            if q in r["skills"]:
                print(f"{r['title']}  — p.{r['printed_page']}")
        return
    r = dict(resolve(rows, q))
    if a.cmd == "related":
        print(f"# {r['title']} (p.{r['printed_page']})")
        print("\nCross-references out:")
        for x in r["xrefs"]:
            print("  ->", x)
        print("\nReferenced by:")
        for o in rows:
            if r["title"] in o["xrefs"]:
                print("  <-", o["title"])
        return
    if a.extra:
        r["pdf_last"] = min(r["pdf_last"] + a.extra, 4964)
        r["_nocache"] = True
    pdf = find_pdf(a.pdf)
    if not pdf:
        sys.exit("PDF not found — set EDBS_PDF=/path/to/edbs.pdf (or pass --pdf).")
    if a.raw:
        print(f"# EDBS 2e — {r['title']} (raw pdf pp.{r['pdf_first']}-{r['pdf_last']})\n")
        print(extract_pages(pdf, r["pdf_first"], r["pdf_last"])[:a.max_chars])
        return
    txt = entry_text(rows, r, pdf)
    if a.cmd == "sections":
        print("\n".join(k for k in split_sections(txt) if k != "_head"))
        return
    if a.section:
        secs = split_sections(txt)
        k = next((k for k in secs if norm(k) == norm(a.section)), None)
        if not k:
            sys.exit(f"Section {a.section!r} not in entry; have: {', '.join(x for x in secs if x != '_head')}")
        txt = f"{k}\n{secs[k]}"
    head = f"# EDBS 2e — {r['title']} (printed p.{r['printed_page']}, pdf pp.{r['pdf_first']}-{r['pdf_last']})\n"
    print(head + txt[:a.max_chars])
    if len(txt) > a.max_chars:
        print(f"\n[... truncated at {a.max_chars} chars; use --max-chars or --section]")


if __name__ == "__main__":
    main()
