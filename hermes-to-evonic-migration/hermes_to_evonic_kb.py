#!/usr/bin/env python3
"""Convert Hermes memories + skills into an Evonic knowledge base (markdown docs with frontmatter).

Run as root on the host that holds ~/.hermes (it reads credentials-bearing text and copies it AS IS, by the user's
explicit choice; the output directory is therefore created 0700 and must never be committed anywhere).

  hermes_to_evonic_kb.py --hermes /root/.hermes --out /srv/migrate/stage [--include-archive] [--dry-run]

Output layout (Evonic allows docs at the root or in a collection folder ONE level under kb/):
  hermes-memory/index.md  + hermes-memory/<NN>-<slug>.md      one doc per entry of MEMORY.md and USER.md (split on the paragraph sign)
  hermes-skills/index.md  + hermes-skills/<category>-<name>.md   one doc per Hermes SKILL.md (body kept verbatim)

Every doc has the frontmatter Evonic enforces: title, description, type. Strings are written with json.dumps, which is
valid YAML, so quotes/colons in Hermes descriptions cannot break the frontmatter. Stdlib only.
"""
import argparse, json, os, re, sys, unicodedata
from collections import Counter, defaultdict

MAX_FILE = 1024 * 1024
PROFILE = None   # set by the caller to tag docs with the Hermes profile they came from


def slugify(s, n=60):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:n].strip("-") or "doc"


def split_fm(text):
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?", text, re.S)
    return (m.group(1), text[m.end():]) if m else (None, text)


def fm_scalar(fm, key):
    """Top-level scalar from a YAML-ish frontmatter block (quoted, plain, or folded/literal block)."""
    m = re.search(rf"^{key}:[ \t]*(.*)$", fm, re.M)
    if not m:
        return None
    v = m.group(1).strip()
    if v in (">", "|", ">-", "|-", ">+", "|+") or v == "":
        rest = fm[m.end():].split("\n")[1:]
        lines = []
        for ln in rest:
            if ln.startswith((" ", "\t")):
                lines.append(ln.strip())
            else:
                break
        return " ".join(l for l in lines if l) or None
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return v or None


def fm_tags(fm):
    m = re.search(r"^\s*tags:[ \t]*\[(.*?)\]", fm, re.M | re.S)
    if m:
        return [t.strip().strip("\"'") for t in m.group(1).split(",") if t.strip()]
    m = re.search(r"^\s*tags:[ \t]*\n((?:[ \t]*-[ \t]*.+\n?)+)", fm, re.M)
    if m:
        return [re.sub(r"^[ \t]*-[ \t]*", "", l).strip().strip("\"'") for l in m.group(1).splitlines() if l.strip()]
    return []


def first_para(body, limit=200):
    for blk in re.split(r"\n\s*\n", body.strip()):
        t = re.sub(r"^#+\s*", "", blk.strip()).replace("\n", " ")
        if t and not t.startswith(("```", "|", "---")):
            return t[:limit]
    return "Migrated from Hermes."


def doc(title, description, dtype, tags, source, body):
    head = ["---", f"title: {json.dumps(title, ensure_ascii=False)}",
            f"description: {json.dumps(description[:300], ensure_ascii=False)}", f"type: {dtype}"]
    if PROFILE:
        tags = list(tags) + [f"profile-{PROFILE}"]
        source = source.replace("hermes:", f"hermes[{PROFILE}]:", 1)
    if tags:
        head.append(f"tags: {json.dumps(sorted(set(tags)), ensure_ascii=False)}")
    head.append(f"source: {json.dumps(source, ensure_ascii=False)}")
    head.append("---")
    return "\n".join(head) + "\n\n" + body.strip() + "\n"


def write(path, content, stats):
    if len(content.encode()) > MAX_FILE:
        stats["too_big"] += 1
        content = content.encode()[:MAX_FILE - 200].decode("utf-8", "ignore") + "\n\n[truncated at 1 MB by the migration]\n"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)


def migrate_memories(hermes, out, dry, stats):
    entries = []
    for fname, label in (("MEMORY.md", "MEMORY"), ("USER.md", "USER")):
        p = os.path.join(hermes, "memories", fname)
        if not os.path.isfile(p):
            continue
        for i, raw in enumerate(re.split(r"\n§\n|\n§$", open(p, encoding="utf-8").read())):
            raw = raw.strip().strip("§").strip()
            if raw:
                entries.append((label, i + 1, raw))
    links = []
    for n, (label, i, raw) in enumerate(entries, 1):
        words = re.sub(r"\s+", " ", raw).split(" ")
        title = f"Hermes {label.lower()} {i:02d}: " + " ".join(words[:7])
        name = f"{n:02d}-{label.lower()}-{slugify(' '.join(words[:6]), 40)}"
        body = raw + f"\n\n_Entry {i} of Hermes `memories/{label}.md`._"
        tags = ["hermes-memory", f"hermes-{label.lower()}"]
        links.append(f"- [[{title}]]")
        if not dry:
            write(os.path.join(out, "hermes-memory", name + ".md"),
                  doc(title, re.sub(r"\s+", " ", raw)[:200], "note", tags, f"hermes:memories/{label}.md#{i}", body), stats)
        stats["memory_docs"] += 1
    if not dry and entries:
        write(os.path.join(out, "hermes-memory", "index.md"),
              doc("Hermes memory (imported)", "Entries copied from Hermes MEMORY.md and USER.md, one note each.", "group",
                  ["hermes-memory"], "hermes:memories", "Notes the Hermes agent kept about the homelab and the user.\n\n" + "\n".join(links)), stats)


def migrate_skills(hermes, out, include_archive, dry, stats):
    root = os.path.join(hermes, "skills")
    found = []
    for dp, dn, fn in os.walk(root):
        dn.sort()
        if "SKILL.md" in fn:
            rel = os.path.relpath(dp, root)
            arch = rel.split(os.sep)[0] == ".archive"
            if arch and not include_archive:
                stats["skipped_archive"] += 1
                continue
            found.append((rel, dp, arch))
    found.sort()
    title_count = Counter()
    prepared = []
    for rel, dp, arch in found:
        text = open(os.path.join(dp, "SKILL.md"), encoding="utf-8").read()
        fm, body = split_fm(text)
        if fm is None:
            stats["no_frontmatter"] += 1
        name = (fm_scalar(fm, "name") if fm else None) or os.path.basename(dp)
        desc = (fm_scalar(fm, "description") if fm else None) or first_para(body)
        parts = rel.split(os.sep)
        cat = parts[0].lstrip(".") if len(parts) > 1 else "general"
        tags = (fm_tags(fm) if fm else []) + ["hermes-skill", f"category-{cat}"] + (["archived"] if arch else [])
        title_count[name] += 1
        prepared.append([rel, dp, name, cat, desc, tags, body, arch])
    seen = Counter()
    links = defaultdict(list)
    used_files = set()
    for rel, dp, name, cat, desc, tags, body, arch in prepared:
        title = name if title_count[name] == 1 else f"{name} ({cat})"
        if title_count[name] > 1:
            stats["renamed_dupes"] += 1
        fname = slugify(f"{cat}-{os.path.basename(dp)}", 70)
        if fname in used_files:
            seen[fname] += 1
            fname = f"{fname}-{seen[fname]}"
        used_files.add(fname)
        extras = sorted(f for f in os.listdir(dp) if f != "SKILL.md")
        if extras:
            stats["with_extra_files"] += 1
            shown = ", ".join(f"`{e}`" for e in extras[:15]) + (f" and {len(extras) - 15} more" if len(extras) > 15 else "")
            body += f"\n\n---\n_Migrated from the Hermes skill `{rel}`. Other files in that skill directory, not migrated: {shown}._"
        else:
            body += f"\n\n---\n_Migrated from the Hermes skill `{rel}`._"
        links[cat].append(f"- [[{title}]]")
        if not dry:
            write(os.path.join(out, "hermes-skills", fname + ".md"),
                  doc(title, desc, "note", tags, f"hermes:skills/{rel}", body), stats)
        stats["skill_docs"] += 1
    if not dry and prepared:
        idx = "Runbooks the Hermes agent used, one note per skill (body copied verbatim).\n"
        for cat in sorted(links):
            idx += f"\n## {cat}\n" + "\n".join(links[cat]) + "\n"
        write(os.path.join(out, "hermes-skills", "index.md"),
              doc("Hermes skills (imported)", "Hermes SKILL.md runbooks imported as notes, grouped by category.", "group",
                  ["hermes-skill"], "hermes:skills", idx), stats)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hermes", default="/root/.hermes")
    ap.add_argument("--out", required=True)
    ap.add_argument("--include-archive", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    stats = Counter()
    if not a.dry_run:
        os.makedirs(a.out, mode=0o700, exist_ok=True)
        os.chmod(a.out, 0o700)
    migrate_memories(a.hermes, a.out, a.dry_run, stats)
    migrate_skills(a.hermes, a.out, a.include_archive, a.dry_run, stats)
    print(json.dumps(dict(stats), indent=1))


if __name__ == "__main__":
    main()
