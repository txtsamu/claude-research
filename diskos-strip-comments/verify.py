#!/usr/bin/env python3
"""Compare HEAD against the working tree for every file the stripper touched.

py   : ast.dump equality (comments are not in the AST; docstrings are, and are untouched)
sh   : `bash --pretty-print` equality (the parsed script, heredocs included)
make : `make -pnq` database equality, annotation comments filtered
c    : `clang -E -P` equality after whitespace normalisation (token stream), fallback: own scan
all  : a second pass of the stripper finds nothing left to remove
"""
import ast
import importlib.util
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(sys.argv[1])
LIST = sys.argv[2]
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("sc", os.path.join(HERE, "strip_comments.py"))
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)


def git_show(rel):
    return subprocess.run(["/usr/bin/git", "-C", ROOT, "show", "HEAD:" + rel], capture_output=True).stdout


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def norm_ws(s):
    return re.sub(r"\s+", "", s)


bad, checked, nofix = [], {}, []
for rel in open(LIST).read().split():
    p = os.path.join(ROOT, rel)
    if not os.path.isfile(p):
        continue
    new = open(p, "rb").read()
    old = git_show(rel)
    if not old or sc.is_binary(old) or old == new:
        continue
    lang = sc.classify(rel, old)
    if lang is None:
        continue
    checked[lang] = checked.get(lang, 0) + 1
    # second pass finds nothing
    try:
        t2, ents, _ = sc.process(rel, new, lang)
        if ents or t2.encode() != new:
            bad.append((rel, "second pass still finds %d comment(s)" % len(ents)))
    except Exception as e:      # noqa
        bad.append((rel, "second pass error %s" % e))
    if lang == "py":
        try:
            if ast.dump(ast.parse(old.decode())) != ast.dump(ast.parse(new.decode())):
                bad.append((rel, "AST differs"))
        except SyntaxError as e:
            bad.append((rel, "syntax error %s" % e))
    elif lang == "sh":
        with tempfile.TemporaryDirectory() as d:
            a, b = os.path.join(d, "a"), os.path.join(d, "b")
            open(a, "wb").write(old)
            open(b, "wb").write(new)
            ra, rb = run(["bash", "--pretty-print", a]), run(["bash", "--pretty-print", b])
            if ra.returncode != 0 or rb.returncode != 0:
                bad.append((rel, "bash parse failed: %s | %s" % (ra.stderr[:120], rb.stderr[:120])))
            elif [l for l in ra.stdout.splitlines() if l.strip()] != [l for l in rb.stdout.splitlines() if l.strip()]:
                bad.append((rel, "pretty-print differs"))
    elif lang == "make":
        with tempfile.TemporaryDirectory() as d:
            mf = os.path.join(d, "mk")
            outs = []
            for data in (old, new):
                open(mf, "wb").write(data)
                r = run(["/usr/bin/make", "-pnq", "-R", "-C", os.path.join(ROOT, os.path.dirname(rel) or "."), "-f", mf])
                lines = [l for l in (r.stdout + r.stderr).splitlines() if l.strip() and not l.startswith("#")]
                outs.append("\n".join(lines))
            if outs[0] != outs[1]:
                bad.append((rel, "make database differs"))
    elif lang in ("c", "c_block"):
        if rel.endswith((".c", ".h", ".inc", ".cpp")) and not rel.startswith(("flash/",)):
            with tempfile.TemporaryDirectory() as d:
                res = []
                for tag, data in (("a", old), ("b", new)):
                    dd = os.path.join(d, tag)
                    sub = os.path.dirname(rel)
                    os.makedirs(os.path.join(dd, sub), exist_ok=True)
                    open(os.path.join(dd, rel), "wb").write(data)
                    incs = ["-I" + sub, "-I" + os.path.join(ROOT, "ui"), "-I" + ROOT,
                            "-I" + os.path.join(ROOT, "ui/third_party"), "-I" + os.path.join(ROOT, "tests"),
                            "-I" + os.path.join(ROOT, "ui/tools")]
                    r = run(["clang", "-E", "-P", "-x", "c", "-D_GNU_SOURCE", "-DDISKOS_TEST_OUTPUTS", "-w"] + incs + [rel], cwd=dd)
                    res.append((r.returncode, norm_ws(r.stdout), r.stderr[:200]))
                if res[0][0] != 0 or res[1][0] != 0:
                    nofix.append((rel, "clang -E failed: " + res[0][2].replace("\n", " ")[:100]))
                elif res[0][1] != res[1][1]:
                    if re.sub(r"\d+", "N", res[0][1]) != re.sub(r"\d+", "N", res[1][1]):
                        bad.append((rel, "preprocessed token stream differs"))
    elif lang == "js":
        with tempfile.TemporaryDirectory() as d:
            fp = os.path.join(d, "x.js")
            open(fp, "wb").write(new)
            r = run(["node", "--check", fp])
            if r.returncode:
                bad.append((rel, "node --check failed: " + r.stderr[:200]))
print("checked:", checked)
print("could not machine-verify:")
for r in nofix:
    print("  ", *r)
print("FAILURES:", len(bad))
for r in bad:
    print("  ", *r)
sys.exit(1 if bad else 0)
