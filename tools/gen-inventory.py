#!/usr/bin/env python3
"""Regenerate the Inventory section of README.md from the files on disk.

Usage:
  python3 tools/gen-inventory.py          # rewrite README.md between the markers
  python3 tools/gen-inventory.py --check  # exit 1 if README.md is out of date

Everything in the inventory is read from the repo itself: skill frontmatter and
reference files, agent frontmatter (model, tools, preloaded skills), rules and
commands. Only the skill *grouping* below is curated; a skill missing from it
is listed under "Other" so nothing is silently dropped.
"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
G = os.path.join(ROOT, "global", ".claude")
LIB = os.path.join(G, "skill-library")
README = os.path.join(ROOT, "README.md")
START, END = "<!-- INVENTORY:START -->", "<!-- INVENTORY:END -->"

GROUPS = [
    ("Query pipeline", ["query-plan-design", "sql-frontend", "query-optimizer", "join-algorithms",
                        "query-execution-advanced", "cardinality-and-statistics", "materialized-views-ivm"]),
    ("Foundations", ["dbms-architecture", "relational-theory", "sql-semantics-and-active-rules"]),
    ("Storage & access methods", ["columnar-arrow-layout", "storage-and-indexing", "page-and-file-format",
                                  "lsm-storage", "storage-devices-and-io", "index-structures-catalog",
                                  "multidimensional-and-similarity-indexing"]),
    ("Transactions & durability", ["transactions-and-recovery", "concurrency-control-theory",
                                   "recovery-and-durability"]),
    ("Scale-out", ["parallel-distributed-execution", "parallel-database-systems", "distributed-dbms-design",
                   "replication-and-consistency", "replication-protocols", "distributed-consensus",
                   "distributed-transactions"]),
    ("Analytical & specialised engines", ["olap-and-warehouse-engines", "stream-processing-engines",
                                          "temporal-databases", "beyond-relational-engines"]),
    ("Operations & safety", ["query-engine-testing", "tuning-and-benchmarking", "database-security-internals"]),
    ("Literature", ["edbs-reference"]),
]


def frontmatter(path):
    s = open(path, encoding="utf-8").read()
    m = re.match(r"---\n(.*?)\n---\n", s, re.S)
    fm, body = (m.group(1), s[m.end():]) if m else ("", s)
    out, key = {}, None
    for line in fm.splitlines():
        if re.match(r"^\s+-\s+", line) and key:
            out.setdefault(key, []).append(line.split("-", 1)[1].strip())
        elif ":" in line and not line.startswith(" "):
            key, val = line.split(":", 1)
            key, val = key.strip(), val.strip().strip('"')
            out[key] = val if val else []
    return out, body


def lines(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return sum(1 for _ in f)


def summary(desc, limit=240):
    d = re.sub(r"^Use (this )?when\s+", "", desc.strip())
    d = re.split(r"\s+Triggers? on\b", d, maxsplit=1)[0].strip().rstrip(".,;:")
    if len(d) > limit:
        d = d[:limit].rsplit(" ", 1)[0].rstrip(",;:(") + " …"
    return d[:1].upper() + d[1:]


def h1(path):
    for line in open(path, encoding="utf-8"):
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def md_escape(s):
    return s.replace("|", "\\|")


def build():
    skills = sorted(d for d in os.listdir(LIB) if os.path.isfile(os.path.join(LIB, d, "SKILL.md")))
    agents = sorted(f[:-3] for f in os.listdir(os.path.join(LIB, "agents")) if f.endswith(".md"))
    ag = {a: frontmatter(os.path.join(LIB, "agents", a + ".md"))[0] for a in agents}
    preloaded_by = {s: [a for a in agents if s in (ag[a].get("skills") or [])] for s in skills}

    info, tot_files, tot_lines = {}, 0, 0
    for s in skills:
        d = os.path.join(LIB, s)
        fm, _ = frontmatter(os.path.join(d, "SKILL.md"))
        files = [os.path.join(r, f) for r, _, fs in os.walk(d) for f in fs]
        refs = sorted(os.path.splitext(os.path.basename(f))[0] for f in files
                      if os.sep + "references" + os.sep in f and f.endswith(".md")
                      and not f.endswith("edbs-entries.md"))
        scripts = sorted(os.path.relpath(f, d) for f in files if os.sep + "scripts" + os.sep in f)
        extra = sorted(os.path.basename(f) for f in files
                       if os.sep + "references" + os.sep in f and not f.endswith(".md"))
        n = sum(lines(f) for f in files if f.endswith((".md", ".py", ".slt")))
        tot_files += len(files); tot_lines += n
        info[s] = dict(summary=summary(fm.get("description", "")),
                       source="EDBS" if os.path.exists(os.path.join(d, "references", "edbs-entries.md"))
                       or s == "edbs-reference" else "Core",
                       refs=refs, scripts=scripts, extra=extra, files=len(files), lines=n)

    grouped = [(g, [s for s in ss if s in info]) for g, ss in GROUPS]
    known = {s for _, ss in grouped for s in ss}
    if set(skills) - known:
        grouped.append(("Other", sorted(set(skills) - known)))

    core = sum(1 for s in skills if info[s]["source"] == "Core")
    out = [START,
           "<!-- Generated by tools/gen-inventory.py from the files on disk. Do not edit by hand;"
           " run `python3 tools/gen-inventory.py` after changing skills, agents, rules or commands. -->",
           "",
           f"**{len(skills)} skills** ({core} core, {len(skills) - core} EDBS-based) · "
           f"**{len(agents)} agents** · **{len(os.listdir(os.path.join(LIB, 'rules')))} library rules** · "
           f"**{len([f for f in os.listdir(os.path.join(G, 'commands')) if f.endswith('.md')])} commands** — "
           f"{tot_files} skill files, {tot_lines:,} lines.",
           "",
           "*Source*: **Core** = built from *How Query Engines Work*, *Database Systems: The Complete Book* and "
           "*Database Internals*; **EDBS** = built from the *Encyclopedia of Database Systems*, 2nd ed. "
           "(has `references/edbs-entries.md` mapping each skill to its source entries).",
           "",
           "### Skills",
           "",
           "All skills live in `global/.claude/skill-library/<skill>/`.",
           ""]
    for g, ss in grouped:
        out += [f"#### {g}", "",
                "| Skill | Source | What it covers | Deep-dive references | Lines | Preloaded by |",
                "|---|---|---|---|---:|---|"]
        for s in ss:
            i = info[s]
            refs = ", ".join(f"`{r}`" for r in i["refs"]) or "—"
            if i["scripts"] or i["extra"]:
                refs += "<br>+ " + ", ".join(f"`{x}`" for x in i["scripts"] + i["extra"])
            pre = ", ".join(f"`{a}`" for a in preloaded_by[s]) or "—"
            out.append(f"| `{s}` | {i['source']} | {md_escape(i['summary'])} | {refs} | {i['lines']:,} | {pre} |")
        out.append("")

    out += ["### Agents", "",
            "All agents live in `global/.claude/skill-library/agents/<agent>.md` and install to a project's "
            "`.claude/agents/`. Install every skill an agent preloads.", "",
            "| Agent | Model | Tools | Preloads skills | Use for |",
            "|---|---|---|---|---|"]
    for a in agents:
        fm = ag[a]
        tools = fm.get("tools") or "all (inherited)"
        if isinstance(tools, list):
            tools = ", ".join(tools)
        pre = ", ".join(f"`{s}`" for s in (fm.get("skills") or [])) or "—"
        missing = [s for s in (fm.get("skills") or []) if s not in info]
        if missing:
            pre += " ⚠ missing: " + ", ".join(missing)
        out.append(f"| `{a}` | {fm.get('model', 'inherit')} | {md_escape(tools)} | {pre} | "
                   f"{md_escape(fm.get('description', ''))} |")
    out.append("")

    out += ["### Rules", "", "| File | Installs to | Purpose |", "|---|---|---|"]
    for f in sorted(os.listdir(os.path.join(G, "rules"))):
        out.append(f"| `global/.claude/rules/{f}` | `~/.claude/rules/` (global) | {md_escape(h1(os.path.join(G, 'rules', f)))} |")
    for f in sorted(os.listdir(os.path.join(LIB, "rules"))):
        out.append(f"| `global/.claude/skill-library/rules/{f}` | project `.claude/rules/` (via picker) | "
                   f"{md_escape(h1(os.path.join(LIB, 'rules', f)))} |")
    out += ["", "### Commands", "", "| Command | File | Purpose |", "|---|---|---|"]
    for f in sorted(os.listdir(os.path.join(G, "commands"))):
        if f.endswith(".md"):
            t = h1(os.path.join(G, "commands", f))
            cmd, _, purpose = t.partition("—")
            out.append(f"| `{cmd.strip()}` | `global/.claude/commands/{f}` | {md_escape(purpose.strip() or t)} |")
    out += ["", "### Tools", "", "| Tool | Purpose |", "|---|---|",
            "| `global/.claude/bin/claude-skills-init` | Interactive picker: installs chosen skills, agents and rules into a project |",
            "| `global/.claude/skill-library/edbs-reference/scripts/edbs.py` | Search the EDBS index; print any entry from your own PDF (`EDBS_PDF`) |",
            "| `tools/gen-inventory.py` | Regenerates this inventory (`--check` fails if it is stale) |",
            "", END]
    return "\n".join(out)


def main():
    readme = open(README, encoding="utf-8").read()
    if START not in readme or END not in readme:
        sys.exit(f"README.md needs {START} and {END} markers")
    new = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: build(), readme, flags=re.S)
    if "--check" in sys.argv:
        if new != readme:
            sys.exit("README.md inventory is stale: run python3 tools/gen-inventory.py")
        print("inventory up to date")
        return
    if new != readme:
        open(README, "w", encoding="utf-8").write(new)
        print("README.md inventory updated")
    else:
        print("inventory already up to date")


if __name__ == "__main__":
    main()
