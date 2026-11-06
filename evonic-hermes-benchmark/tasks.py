"""Benchmark task suite: 16 tasks, deterministic fixtures, programmatic checkers.

Every task has:
  setup(workdir)            create the fixture files
  prompt                    text sent verbatim to the agent ({workdir} is substituted)
  check(workdir, final)     -> (passed: bool, detail: str); no LLM judge, no network
  solve(workdir)            reference solution, used only by selftest.py to prove the
                            checker accepts a correct answer (and rejects an empty one)

Stdlib only. Fixtures are seeded so every run of every agent sees identical inputs.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

PY = sys.executable or "python3"


@dataclass
class Task:
    id: str
    category: str
    prompt: str
    setup: Callable[[Path], None]
    check: Callable[[Path, str], tuple[bool, str]]
    solve: Callable[[Path], None]
    timeout_s: int = 600


TASKS: list[Task] = []


def task(id, category, prompt, timeout_s=600):
    """Decorator collecting (setup, check, solve) triples defined as one class-like function."""
    def deco(fn):
        setup, check, solve = fn()
        TASKS.append(Task(id, category, prompt.strip(), setup, check, solve, timeout_s))
        return fn
    return deco


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def _run(cmd, cwd, timeout=60):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


# ───────────────────────────── A: file / shell tool use ─────────────────────────────

@task("A1_create_files", "tool_use", """
Work only inside {workdir}. Create the file hello.txt containing exactly the text:
hello benchmark
Also create the file dir/sub/notes.md (create the directories) whose first line is "# Notes"
and whose second line is "owner: bench". When done, reply with the word DONE.
""")
def _a1():
    def setup(w): w.mkdir(parents=True, exist_ok=True)
    def check(w, final):
        h = w / "hello.txt"; n = w / "dir/sub/notes.md"
        if not h.is_file(): return False, "hello.txt missing"
        if _read(h).strip() != "hello benchmark": return False, f"hello.txt content {_read(h)!r}"
        if not n.is_file(): return False, "dir/sub/notes.md missing"
        lines = _read(n).splitlines()
        if lines[:2] != ["# Notes", "owner: bench"]: return False, f"notes lines {lines[:3]}"
        return True, "ok"
    def solve(w):
        (w / "hello.txt").write_text("hello benchmark\n")
        (w / "dir/sub").mkdir(parents=True); (w / "dir/sub/notes.md").write_text("# Notes\nowner: bench\n")
    return setup, check, solve


def _a2_files():
    rnd = random.Random(2)
    words = "alpha beta gamma delta river stone cloud ember quartz maple".split()
    out = {}
    for i in range(12):
        body = [" ".join(rnd.choice(words) for _ in range(8)) for _ in range(5)]
        if i in (1, 4, 5, 9, 11):
            body.insert(rnd.randrange(len(body)), "TODO: fix this")
        if i in (2, 7):
            body.append("todo lowercase must not count")
        out[f"note_{i:02d}.txt"] = "\n".join(body) + "\n"
    return out


@task("A2_count_grep", "tool_use", """
Work only inside {workdir}. It contains text files. Find which files contain the exact,
case-sensitive word TODO. Write the number of such files as an integer on its own to answer.txt,
and write their file names, one per line, sorted alphabetically, to todo_files.txt.
""")
def _a2():
    files = _a2_files()
    gold = sorted(n for n, b in files.items() if re.search(r"\bTODO\b", b))
    def setup(w):
        w.mkdir(parents=True, exist_ok=True)
        for n, b in files.items(): (w / n).write_text(b)
    def check(w, final):
        a = w / "answer.txt"; t = w / "todo_files.txt"
        if not a.is_file() or not t.is_file(): return False, "output file missing"
        if _read(a).strip() != str(len(gold)): return False, f"answer {_read(a).strip()!r} != {len(gold)}"
        got = [l.strip() for l in _read(t).splitlines() if l.strip()]
        if got != gold: return False, f"list {got} != {gold}"
        return True, "ok"
    def solve(w):
        (w / "answer.txt").write_text(f"{len(gold)}\n"); (w / "todo_files.txt").write_text("\n".join(gold) + "\n")
    return setup, check, solve


def _a3_rows():
    rnd = random.Random(3)
    regions = ["north", "south", "east", "west"]
    return [(f"2026-0{1 + i % 9}-{1 + i % 27:02d}", rnd.choice(regions), round(rnd.uniform(10, 500), 2)) for i in range(40)]


@task("A3_csv_to_json", "tool_use", """
Work only inside {workdir}. sales.csv has the columns date,region,revenue. Write summary.json: a single
JSON object that maps each region name to its total revenue, rounded to 2 decimals (numbers, not strings).
""")
def _a3():
    rows = _a3_rows()
    gold: dict[str, float] = {}
    for _, r, v in rows: gold[r] = round(gold.get(r, 0) + v, 2)
    def setup(w):
        w.mkdir(parents=True, exist_ok=True)
        with open(w / "sales.csv", "w", newline="") as f:
            cw = csv.writer(f); cw.writerow(["date", "region", "revenue"]); cw.writerows(rows)
    def check(w, final):
        p = w / "summary.json"
        if not p.is_file(): return False, "summary.json missing"
        try: got = json.loads(_read(p))
        except Exception as e: return False, f"invalid json: {e}"
        if not isinstance(got, dict) or set(got) != set(gold): return False, f"keys {sorted(got) if isinstance(got, dict) else got}"
        bad = {k: (got[k], gold[k]) for k in gold if not isinstance(got[k], (int, float)) or abs(got[k] - gold[k]) > 0.011}
        return (not bad), ("ok" if not bad else f"wrong totals {bad}")
    def solve(w): (w / "summary.json").write_text(json.dumps(gold))
    return setup, check, solve


@task("A4_organize_by_ext", "tool_use", """
Work only inside {workdir}. It holds a flat set of files. Move every file into a subdirectory named after its
extension without the dot (for example photo.jpg goes to jpg/photo.jpg), keeping file names unchanged.
Then write manifest.txt with one line per subdirectory in the form "ext: count" (for example "jpg: 4"),
sorted alphabetically by ext. Do not delete any file.
""")
def _a4():
    names = ([f"img_{i}.jpg" for i in range(4)] + [f"doc_{i}.txt" for i in range(5)] +
             [f"run_{i}.log" for i in range(3)] + [f"tbl_{i}.csv" for i in range(3)])
    def setup(w):
        w.mkdir(parents=True, exist_ok=True)
        for n in names: (w / n).write_text(f"content of {n}\n")
    def check(w, final):
        for n in names:
            ext = n.rsplit(".", 1)[1]; p = w / ext / n
            if not p.is_file(): return False, f"{ext}/{n} missing"
            if _read(p) != f"content of {n}\n": return False, f"{n} content changed"
            if (w / n).exists(): return False, f"{n} still in top level"
        m = w / "manifest.txt"
        if not m.is_file(): return False, "manifest.txt missing"
        want = {}
        for n in names: want[n.rsplit(".", 1)[1]] = want.get(n.rsplit(".", 1)[1], 0) + 1
        lines = [l.strip() for l in _read(m).splitlines() if l.strip()]
        exp = [f"{k}: {want[k]}" for k in sorted(want)]
        return (lines == exp), ("ok" if lines == exp else f"manifest {lines} != {exp}")
    def solve(w):
        want = {}
        for n in names:
            ext = n.rsplit(".", 1)[1]; (w / ext).mkdir(exist_ok=True); shutil.move(str(w / n), str(w / ext / n))
            want[ext] = want.get(ext, 0) + 1
        (w / "manifest.txt").write_text("\n".join(f"{k}: {want[k]}" for k in sorted(want)) + "\n")
    return setup, check, solve


# ───────────────────────────── B: coding ─────────────────────────────

@task("B1_implement_slugify", "coding", """
Work only inside {workdir}. slugify.py contains a stub function slugify(text). Implement it exactly as its
docstring specifies, and make `python3 -m unittest -v` pass in that directory. Do not modify test_slugify.py.
""")
def _b1():
    stub = '''def slugify(text: str) -> str:
    """Return a URL slug.

    Rules: lowercase; replace every run of characters that are not a-z or 0-9 with a single "-";
    strip leading/trailing "-"; if the result is empty return "n-a"; truncate to at most 20 characters
    and strip a trailing "-" again after truncating.
    """
    raise NotImplementedError
'''
    tests = '''import unittest
from slugify import slugify

class T(unittest.TestCase):
    def test_basic(self): self.assertEqual(slugify("Hello World"), "hello-world")
    def test_runs(self): self.assertEqual(slugify("a  --  b"), "a-b")
    def test_empty(self): self.assertEqual(slugify("!!!"), "n-a")

if __name__ == "__main__":
    unittest.main()
'''
    hidden = [("  Already-Slug  ", "already-slug"), ("Caf\u00e9 au lait", "caf-au-lait"),
              ("x" * 30, "x" * 20), ("abcdefghi-jklmnopqrs-tuv", "abcdefghi-jklmnopqrs"),
              ("2026/11/06 report", "2026-11-06-report"), ("", "n-a"), ("---", "n-a"),
              ("a" * 19 + " b", "a" * 19)]
    def setup(w):
        w.mkdir(parents=True, exist_ok=True); (w / "slugify.py").write_text(stub); (w / "test_slugify.py").write_text(tests)
    def check(w, final):
        if hashlib.sha1(_read(w / "test_slugify.py").encode()).hexdigest() != hashlib.sha1(tests.encode()).hexdigest():
            return False, "test file was modified"
        code = "import sys; sys.path.insert(0,'.'); from slugify import slugify\nimport json; print(json.dumps([slugify(t) for t in json.load(open('cases.json'))]))"
        with tempfile.TemporaryDirectory() as td:
            Path(td, "cases.json").write_text(json.dumps([t for t, _ in hidden]))
            shutil.copy(w / "slugify.py", td)
            r = _run([PY, "-c", code], td)
        if r.returncode: return False, f"import/run failed: {r.stderr[-200:]}"
        got = json.loads(r.stdout); want = [e for _, e in hidden]
        bad = [(h[0], g, e) for h, g, e in zip(hidden, got, want) if g != e]
        return (not bad), ("ok" if not bad else f"hidden cases wrong: {bad[:2]}")
    def solve(w):
        (w / "slugify.py").write_text('''import re
def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not s: return "n-a"
    return s[:20].rstrip("-") or "n-a"
''')
    return setup, check, solve


@task("B2_fix_bug", "coding", """
Work only inside {workdir}. The unit tests in test_inventory.py fail because of bugs in inventory.py.
Fix inventory.py (not the tests) so that `python3 -m unittest -v` passes.
""")
def _b2():
    src = '''def total_value(items):
    """items: list of (name, qty, unit_price). Return total value."""
    total = 0
    for i in range(1, len(items)):
        name, qty, price = items[i]
        total += qty * price
    return total


def low_stock(items, threshold):
    """Names with qty strictly below threshold, sorted alphabetically."""
    return sorted([n for n, q, _ in items if q <= threshold], reverse=True)


def restock(items, name, amount):
    """Return a new list with qty of `name` increased by amount."""
    out = []
    for n, q, p in items:
        if n == name:
            q = q + amount
        out.append((n, q, p))
    return out
'''
    tests = '''import unittest
from inventory import total_value, low_stock, restock

ITEMS = [("bolt", 10, 0.5), ("nut", 3, 0.25), ("gear", 1, 12.0), ("axle", 5, 7.5)]

class T(unittest.TestCase):
    def test_total(self): self.assertAlmostEqual(total_value(ITEMS), 5 + 0.75 + 12 + 37.5)
    def test_low(self): self.assertEqual(low_stock(ITEMS, 5), ["gear", "nut"])
    def test_restock(self): self.assertEqual(restock(ITEMS, "gear", 4)[2], ("gear", 5, 12.0))
    def test_restock_pure(self):
        restock(ITEMS, "gear", 4); self.assertEqual(ITEMS[2], ("gear", 1, 12.0))

if __name__ == "__main__":
    unittest.main()
'''
    def setup(w):
        w.mkdir(parents=True, exist_ok=True); (w / "inventory.py").write_text(src); (w / "test_inventory.py").write_text(tests)
    def check(w, final):
        if _read(w / "test_inventory.py") != tests: return False, "test file was modified"
        r = _run([PY, "-m", "unittest"], w)
        return (r.returncode == 0), ("ok" if r.returncode == 0 else r.stderr[-250:])
    def solve(w):
        s = _read(w / "inventory.py").replace("range(1, len(items))", "range(len(items))").replace("q <= threshold], reverse=True", "q < threshold]")
        (w / "inventory.py").write_text(s)
    return setup, check, solve


@task("B3_write_cli", "coding", """
Work only inside {workdir}. Write a Python 3 script wordfreq.py that takes one argument, a text file path, and prints
the 5 most frequent words (case-insensitive, words are runs of letters a-z) one per line as "word count",
ordered by count descending and then alphabetically for ties. Test it on sample.txt.
""")
def _b3():
    sample = "the cat and the dog and the bird. The end, and so on.\n"
    hidden = ("Apple banana apple Cherry banana apple. cherry! date date date date egg fig fig Fig grape\n" * 3)
    def wf(text):
        from collections import Counter
        c = Counter(re.findall(r"[a-z]+", text.lower()))
        return [f"{w} {n}" for w, n in sorted(c.items(), key=lambda x: (-x[1], x[0]))[:5]]
    def setup(w): w.mkdir(parents=True, exist_ok=True); (w / "sample.txt").write_text(sample)
    def check(w, final):
        s = w / "wordfreq.py"
        if not s.is_file(): return False, "wordfreq.py missing"
        with tempfile.TemporaryDirectory() as td:
            Path(td, "h.txt").write_text(hidden)
            r = _run([PY, str(s), str(Path(td, "h.txt"))], w)
        if r.returncode: return False, f"script failed: {r.stderr[-200:]}"
        got = [l.strip() for l in r.stdout.splitlines() if l.strip()]
        return (got == wf(hidden)), ("ok" if got == wf(hidden) else f"{got} != {wf(hidden)}")
    def solve(w):
        (w / "wordfreq.py").write_text('''import re, sys
from collections import Counter
c = Counter(re.findall(r"[a-z]+", open(sys.argv[1]).read().lower()))
for w, n in sorted(c.items(), key=lambda x: (-x[1], x[0]))[:5]: print(w, n)
''')
    return setup, check, solve


@task("B4_refactor_dedupe", "coding", """
Work only inside {workdir}. parse_line is copy-pasted into several modules. Move it into a new module common.py,
make every other module import it from there, and make sure `python3 -m unittest` still passes.
Do not change the tests. After the refactor, `def parse_line` must appear exactly once in the directory.
""")
def _b4():
    fn = '''def parse_line(line):
    key, _, value = line.partition("=")
    return key.strip(), value.strip()
'''
    mods = {
        "reader.py": fn + '\n\ndef read_pairs(text):\n    return [parse_line(l) for l in text.splitlines() if "=" in l]\n',
        "writer.py": fn + '\n\ndef normalise(line):\n    k, v = parse_line(line)\n    return f"{k}={v}"\n',
        "checker.py": fn + '\n\ndef has_key(line, key):\n    return parse_line(line)[0] == key\n',
    }
    tests = '''import unittest
from reader import read_pairs
from writer import normalise
from checker import has_key

class T(unittest.TestCase):
    def test_all(self):
        self.assertEqual(read_pairs("a = 1\\nbad\\nb=2"), [("a", "1"), ("b", "2")])
        self.assertEqual(normalise(" x =  y "), "x=y")
        self.assertTrue(has_key("k = v", "k"))

if __name__ == "__main__":
    unittest.main()
'''
    def setup(w):
        w.mkdir(parents=True, exist_ok=True)
        for n, b in mods.items(): (w / n).write_text(b)
        (w / "test_all.py").write_text(tests)
    def check(w, final):
        if _read(w / "test_all.py") != tests: return False, "test file was modified"
        defs = sum(len(re.findall(r"^\s*def parse_line\b", _read(p), re.M)) for p in w.glob("*.py"))
        if defs != 1: return False, f"{defs} definitions of parse_line"
        if not (w / "common.py").is_file() or "def parse_line" not in _read(w / "common.py"): return False, "common.py lacks parse_line"
        r = _run([PY, "-m", "unittest"], w)
        return (r.returncode == 0), ("ok" if r.returncode == 0 else r.stderr[-250:])
    def solve(w):
        (w / "common.py").write_text(fn)
        for n in mods:
            s = _read(w / n).replace(fn, "from common import parse_line\n"); (w / n).write_text(s)
    return setup, check, solve


# ───────────────────────────── C: error recovery ─────────────────────────────

@task("C1_broken_script", "recovery", """
Work only inside {workdir}. Running ./run.sh currently fails. Make `./run.sh` exit with status 0 and produce
out/report.txt containing the line OK. You may edit run.sh and create files, but keep the purpose of the script.
""")
def _c1():
    script = '''#!/bin/bash
set -e
python3 gen_report.py > out/report.txt
grep -q OK out/report.txt
'''
    gen = 'print("OK")\n'
    def setup(w):
        w.mkdir(parents=True, exist_ok=True)
        (w / "run.sh").write_text(script.replace("gen_report.py", "gen_reprot.py")); (w / "run.sh").chmod(0o644)
        (w / "gen_report.py").write_text(gen)
    def check(w, final):
        shutil.rmtree(w / "out", ignore_errors=True)
        r = _run(["bash", "./run.sh"], w)
        ok = r.returncode == 0 and (w / "out/report.txt").is_file() and "OK" in _read(w / "out/report.txt")
        return ok, ("ok" if ok else f"rc={r.returncode} {r.stderr[-200:]}")
    def solve(w):
        (w / "run.sh").write_text('#!/bin/bash\nset -e\nmkdir -p out\npython3 gen_report.py > out/report.txt\ngrep -q OK out/report.txt\n')
    return setup, check, solve


@task("C2_bad_config", "recovery", """
Work only inside {workdir}. `python3 app.py` crashes at startup. Fix the problem so that it prints exactly
"service ready port=9090" and exits with status 0. Keep the intended port 9090 from the configuration.
""")
def _c2():
    app = '''import json
cfg = json.load(open("config.json"))
print(f"service ready port={cfg['server']['port']}")
'''
    bad = '{\n  "server": {\n    "port": 9090,\n    "host": "0.0.0.0",\n  },\n  "debug": false\n}\n'
    def setup(w): w.mkdir(parents=True, exist_ok=True); (w / "app.py").write_text(app); (w / "config.json").write_text(bad)
    def check(w, final):
        r = _run([PY, "app.py"], w)
        ok = r.returncode == 0 and r.stdout.strip() == "service ready port=9090"
        return ok, ("ok" if ok else f"rc={r.returncode} out={r.stdout.strip()!r} err={r.stderr[-150:]}")
    def solve(w): (w / "config.json").write_text('{"server": {"port": 9090, "host": "0.0.0.0"}, "debug": false}\n')
    return setup, check, solve


@task("C3_readonly_file", "recovery", """
Work only inside {workdir}. Append the line "reviewed: yes" to the end of data.txt, keeping every existing line.
""")
def _c3():
    body = "id: 7\nstatus: open\nowner: ops\n"
    def setup(w):
        w.mkdir(parents=True, exist_ok=True); (w / "data.txt").write_text(body); (w / "data.txt").chmod(0o444)
    def check(w, final):
        lines = _read(w / "data.txt").splitlines()
        ok = lines == ["id: 7", "status: open", "owner: ops", "reviewed: yes"]
        return ok, ("ok" if ok else f"lines {lines}")
    def solve(w):
        (w / "data.txt").chmod(0o644)
        with open(w / "data.txt", "a") as f: f.write("reviewed: yes\n")
    return setup, check, solve


@task("C4_find_the_config", "recovery", """
Work only inside {workdir}. Somewhere under the directory config/ there is a setting for the database port
(key "port" in the database section of the production settings). Find it and write just the number to db_port.txt.
""")
def _c4():
    def setup(w):
        (w / "config/envs/prod").mkdir(parents=True, exist_ok=True); (w / "config/envs/dev").mkdir(parents=True, exist_ok=True)
        (w / "config/app.yml").write_text("server:\n  port: 8080\ncache:\n  port: 6379\n")
        (w / "config/envs/dev/settings.yml").write_text("database:\n  host: localhost\n  port: 5433\n")
        (w / "config/envs/prod/settings.yml").write_text("database:\n  host: db.internal\n  port: 5432\n")
    def check(w, final):
        p = w / "db_port.txt"
        if not p.is_file(): return False, "db_port.txt missing"
        v = _read(p).strip()
        return (v == "5432"), ("ok" if v == "5432" else f"got {v!r}; prod is 5432, dev is 5433, cache is 6379")
    def solve(w): (w / "db_port.txt").write_text("5432\n")
    # note: the prompt asks for "the" database port; prod is the only non-dev environment, see prompt rule below
    return setup, check, solve


# ───────────────────────────── E: authoring / extraction ─────────────────────────────

_NOTES = """- 09:14 pager fires: checkout latency alert
- 09:20 oncall acks, sees db connections maxed
- 09:41 pool size raised from 50 to 200, no change
- ACTION: add connection pool saturation alert
- 10:05 found slow query from new recommendations job holding locks
- 10:12 job paused, latency recovers
- ACTION: add index on events(user_id, created_at)
- ACTION: run heavy jobs on the replica only
- cause: recommendations job full-table scan after deploy 2026-11-03
"""


@task("E1_postmortem", "authoring", """
Work only inside {workdir}. notes.txt has raw incident notes. Write postmortem.md with exactly these four level-2
headings, in this order: "## Summary", "## Timeline", "## Root cause", "## Action items".
Timeline: one bullet per timestamped note, in chronological order, each keeping its HH:MM time.
Action items: every line that starts with "ACTION:" in the notes becomes a checklist item "- [ ] <text>".
The Summary must be 1 to 3 sentences. Do not invent facts that are not in the notes.
""")
def _e1():
    times = re.findall(r"^- (\d\d:\d\d)", _NOTES, re.M)
    actions = [l[len("- ACTION:"):].strip() for l in _NOTES.splitlines() if l.startswith("- ACTION:")]
    def setup(w): w.mkdir(parents=True, exist_ok=True); (w / "notes.txt").write_text(_NOTES)
    def check(w, final):
        p = w / "postmortem.md"
        if not p.is_file(): return False, "postmortem.md missing"
        t = _read(p)
        heads = re.findall(r"^## (.+)$", t, re.M)
        if heads != ["Summary", "Timeline", "Root cause", "Action items"]: return False, f"headings {heads}"
        tl = t.split("## Timeline")[1].split("## Root cause")[0]
        got_t = re.findall(r"(\d\d:\d\d)", tl)
        if got_t != times: return False, f"timeline times {got_t} != {times}"
        ai = t.split("## Action items")[1]
        items = re.findall(r"^- \[ \] (.+)$", ai, re.M)
        if len(items) != len(actions): return False, f"{len(items)} checklist items != {len(actions)}"
        for a in actions:
            if a.lower() not in " ".join(items).lower(): return False, f"action missing: {a}"
        summ = t.split("## Summary")[1].split("## Timeline")[0].strip()
        n = len([s for s in re.split(r"(?<=[.!?])\s+", summ) if s.strip()])
        if not (1 <= n <= 3): return False, f"summary has {n} sentences"
        if "recommendations" not in t.lower(): return False, "root cause (recommendations job) not mentioned"
        return True, "ok"
    def solve(w):
        tl = "\n".join(f"- {l[2:]}" for l in _NOTES.splitlines() if re.match(r"^- \d\d:\d\d", l))
        ai = "\n".join(f"- [ ] {a}" for a in actions)
        (w / "postmortem.md").write_text(f"## Summary\nCheckout latency spiked until a recommendations job was paused.\n\n## Timeline\n{tl}\n\n## Root cause\nThe recommendations job ran a full-table scan after the deploy.\n\n## Action items\n{ai}\n")
    return setup, check, solve


_LOG = """feat: add dark mode toggle
fix: crash when cart is empty
chore: bump dependencies
feat: export orders as csv
fix: wrong tax on discounted items
fix: timeout on slow networks
chore: update CI image
feat: saved searches
"""


@task("E2_changelog", "authoring", """
Work only inside {workdir}. commits.txt has one commit message per line, each prefixed with its type
(feat, fix or chore). Write CHANGELOG.md with the level-2 headings "## Features", "## Fixes", "## Chores"
in that order. Under each heading put one bullet "- <message without the type prefix>" per commit of that type,
keeping the original order. Every commit appears exactly once.
""")
def _e2():
    groups = {"feat": [], "fix": [], "chore": []}
    for l in _LOG.splitlines():
        t, m = l.split(": ", 1); groups[t].append(m)
    def setup(w): w.mkdir(parents=True, exist_ok=True); (w / "commits.txt").write_text(_LOG)
    def check(w, final):
        p = w / "CHANGELOG.md"
        if not p.is_file(): return False, "CHANGELOG.md missing"
        t = _read(p)
        if re.findall(r"^## (.+)$", t, re.M) != ["Features", "Fixes", "Chores"]: return False, "headings wrong"
        parts = re.split(r"^## .+$", t, flags=re.M)[1:]
        for part, key in zip(parts, ["feat", "fix", "chore"]):
            bullets = [b.strip() for b in re.findall(r"^[-*] (.+)$", part, re.M)]
            if bullets != groups[key]: return False, f"{key}: {bullets} != {groups[key]}"
        return True, "ok"
    def solve(w):
        out = []
        for h, k in (("Features", "feat"), ("Fixes", "fix"), ("Chores", "chore")):
            out.append(f"## {h}\n" + "\n".join(f"- {m}" for m in groups[k]) + "\n")
        (w / "CHANGELOG.md").write_text("\n".join(out))
    return setup, check, solve


_PROSE = ("On Tuesday, Maya Anggraini flew from Jakarta to Surabaya to meet Budi Santoso at the Tunjungan Plaza office of "
          "Nusantara Freight. Later they joined Dr. Lena Fischer, who had arrived from Hamburg for a conference hosted by "
          "Telkom Indonesia in Bandung. Budi mentioned that his brother Rizal works at Pertamina.")
_GOLD_ENT = {("Maya Anggraini", "person"), ("Budi Santoso", "person"), ("Lena Fischer", "person"), ("Rizal", "person"),
             ("Jakarta", "place"), ("Surabaya", "place"), ("Hamburg", "place"), ("Bandung", "place"),
             ("Nusantara Freight", "org"), ("Telkom Indonesia", "org"), ("Pertamina", "org")}


@task("E3_extract_entities", "authoring", """
Work only inside {workdir}. text.txt is a short story. Write entities.json: a JSON list of objects, each with the
keys `name` and `type`, with one object per distinct person, place (cities) and organization mentioned,
where type is exactly `person`, `place` or `org`. Use the full name as it first appears (without titles such as Dr.).
Do not include dates, weekdays or buildings.
""")
def _e3():
    def setup(w): w.mkdir(parents=True, exist_ok=True); (w / "text.txt").write_text(_PROSE + "\n")
    def check(w, final):
        p = w / "entities.json"
        if not p.is_file(): return False, "entities.json missing"
        try: got = json.loads(_read(p))
        except Exception as e: return False, f"invalid json: {e}"
        try: pred = {(e["name"].strip(), e["type"].strip()) for e in got}
        except Exception: return False, "wrong structure"
        tp = len(pred & _GOLD_ENT); prec = tp / len(pred) if pred else 0; rec = tp / len(_GOLD_ENT)
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
        return (f1 >= 0.85), f"F1={f1:.2f} (P={prec:.2f} R={rec:.2f})"
    def solve(w): (w / "entities.json").write_text(json.dumps([{"name": n, "type": t} for n, t in sorted(_GOLD_ENT)]))
    return setup, check, solve


_ARTICLE = ("The city council approved a plan to replace 4,000 streetlights with LED fixtures over three years. "
            "Officials expect the change to cut electricity use by about 60 percent and save roughly 1.2 million dollars "
            "annually in energy and maintenance costs. Residents in two pilot districts reported that the new lights "
            "feel brighter and more even, although a few complained about a colder, bluish tint. Astronomers asked the "
            "council to choose warmer color temperatures and shielded fixtures to limit light pollution. The council "
            "agreed to review the specification after the pilot and to publish yearly savings reports. Funding comes "
            "from a municipal bond and a regional energy grant, and the first installations begin in March.")


@task("E4_constrained_summary", "authoring", """
Work only inside {workdir}. Summarize article.txt in summary.md as exactly 3 bullet points ("- " prefix),
each at most 20 words, with no other text in the file. Together the bullets must mention the savings figure
(1.2 million), the LED switch, and the concern raised by astronomers.
""")
def _e4():
    def setup(w): w.mkdir(parents=True, exist_ok=True); (w / "article.txt").write_text(_ARTICLE + "\n")
    def check(w, final):
        p = w / "summary.md"
        if not p.is_file(): return False, "summary.md missing"
        lines = [l for l in _read(p).splitlines() if l.strip()]
        if len(lines) != 3 or not all(l.startswith("- ") for l in lines): return False, f"{len(lines)} lines / bad prefix"
        for l in lines:
            if len(l[2:].split()) > 20: return False, f"bullet over 20 words: {len(l[2:].split())}"
        t = " ".join(lines).lower()
        miss = [k for k, pat in (("savings", r"1\.2"), ("led", r"\bleds?\b"), ("astronomers", r"astronom")) if not re.search(pat, t)]
        return (not miss), ("ok" if not miss else f"missing {miss}")
    def solve(w):
        (w / "summary.md").write_text("- Council approves replacing 4,000 streetlights with LEDs over three years.\n- Savings of about 1.2 million dollars yearly are expected.\n- Astronomers want warmer, shielded lights to limit light pollution.\n")
    return setup, check, solve


# Evonic rewrites " and ' in user text to curly quotes before the model sees them (backend/normalizer.py), which would
# penalise it on exact-string tasks for a reason unrelated to capability. All prompts therefore carry literals in backticks.
for _t in TASKS:
    _t.prompt = re.sub(r'"([^"\n]*)"', r'`\1`', _t.prompt)
    assert '"' not in _t.prompt and "'" not in _t.prompt, f"quote left in prompt of {_t.id}"

BY_ID = {t.id: t for t in TASKS}
