#!/usr/bin/env python3
"""Strip source comments from the diskOS tree and collect them into comments.md.

usage: strip_comments.py [--apply] [--root DIR] [--list FILE] [--md OUT] [--survey]

Without --apply nothing in the tree is written (the report still goes to --md).
Kept on purpose: shebangs, coding cookies, legal notices (SPDX / Copyright / licence text),
tool directives (noqa, NOLINT, fallthrough, Dockerfile parser directives, ...).
"""
import argparse
import io
import os
import re
import subprocess
import sys
import tokenize

S0, S1 = "", ""
SENT = re.compile(S0 + r"(\d+)" + S1)

LEGAL = re.compile(
    r"SPDX-License-Identifier|SPDX-FileCopyrightText|^\s*Copyright\b|\(C\)\s*\d{4}|GNU General Public|"
    r"Permission is hereby granted|WITHOUT WARRANTY|Licensed under|free software", re.I | re.M)
DIRECTIVE = re.compile(
    r"^\s*(?:noqa\b|type:|pylint|pragma\b|fmt:|isort|mypy|ruff|-\*-|NOLINT|fall(?:s)?[ -]?thr(?:ough|u)\.?\s*$|FALLTHR|"
    r"lint:|coverity|cppcheck|clang-format|vim:|syntax=|escape=|check=|shellcheck|yamllint)", re.I)


THIRD_PARTY = {"ui/sqlite3.c", "ui/sqlite3.h", "ui/jsmn.h", "ui/md5.c", "ui/lv_conf.h"}


def is_binary(data):
    return b"\x00" in data[:8192]


# ----------------------------------------------------------------------------------------------
# language scanners: each returns [(start, end, kind)] of comment spans (kind 'line'|'block')
# ----------------------------------------------------------------------------------------------

def scan_c(t, line_comments=True):
    out, i, n = [], 0, len(t)
    while i < n:
        c = t[i]
        if c == "/" and i + 1 < n and t[i + 1] == "*":
            j = t.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append((i, j, "block"))
            i = j
        elif c == "/" and line_comments and i + 1 < n and t[i + 1] == "/":
            j = i
            while True:
                k = t.find("\n", j)
                if k < 0:
                    j = n
                    break
                if k > 0 and t[k - 1] == "\\":
                    j = k + 1
                    continue
                j = k
                break
            out.append((i, j, "line"))
            i = j
        elif c == '"':
            i += 1
            while i < n and t[i] != '"' and t[i] != "\n":
                i += 2 if t[i] == "\\" else 1
            i += 1
        elif c == "'":
            j = i + 1
            while j < n and t[j] != "'" and t[j] != "\n" and j - i < 12:
                j += 2 if t[j] == "\\" else 1
            if j < n and t[j] == "'":
                i = j + 1
            else:
                i += 1
        else:
            i += 1
    return out


def scan_sh(t, base=0):
    """Shell scanner: quotes, $(...), ${...}, backticks, heredocs. Returns comment spans."""
    out = []
    n = len(t)
    pending = []        # heredoc (delim, strip_tabs) waiting for the next newline

    def skip_squote(i):
        j = t.find("'", i + 1)
        return n if j < 0 else j + 1

    def skip_dquote(i):
        i += 1
        while i < n:
            c = t[i]
            if c == "\\":
                i += 2
            elif c == '"':
                return i + 1
            elif c == "$" and i + 1 < n and t[i + 1] == "(":
                i = scan_code(i + 2, ")")
            elif c == "$" and i + 1 < n and t[i + 1] == "{":
                i = skip_brace(i + 2)
            elif c == "`":
                i = skip_bquote(i)
            else:
                i += 1
        return n

    def skip_bquote(i):
        i += 1
        while i < n:
            if t[i] == "\\":
                i += 2
            elif t[i] == "`":
                return i + 1
            else:
                i += 1
        return n

    def skip_brace(i):
        depth = 1
        while i < n:
            c = t[i]
            if c == "\\":
                i += 2
                continue
            if c == "'":
                i = skip_squote(i)
                continue
            if c == '"':
                i = skip_dquote(i)
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        return n

    def read_heredocs(i):
        # i is just after a newline; consume bodies for pending heredocs
        nonlocal pending
        for delim, strip in pending:
            while i < n:
                k = t.find("\n", i)
                line = t[i:] if k < 0 else t[i:k]
                i = n if k < 0 else k + 1
                cmp = line.lstrip("\t") if strip else line
                if cmp == delim:
                    break
        pending = []
        return i

    def scan_code(i, term):
        depth = 0
        while i < n:
            c = t[i]
            if c == "\\":
                i += 2
            elif c == "'":
                i = skip_squote(i)
            elif c == '"':
                i = skip_dquote(i)
            elif c == "`":
                i = skip_bquote(i)
            elif c == "$":
                nx = t[i + 1] if i + 1 < n else ""
                if nx == "(":
                    if t.startswith("$((", i):
                        j = t.find("))", i + 3)
                        i = n if j < 0 else j + 2
                    else:
                        i = scan_code(i + 2, ")")
                elif nx == "{":
                    i = skip_brace(i + 2)
                elif nx == "'":
                    j = i + 2
                    while j < n and t[j] != "'":
                        j += 2 if t[j] == "\\" else 1
                    i = j + 1
                else:
                    i += 2
            elif c == "#":
                prev = t[i - 1] if i > 0 else "\n"
                if prev in " \t\n;&|(" or (i == 0):
                    k = t.find("\n", i)
                    k = n if k < 0 else k
                    out.append((base + i, base + k, "line"))
                    i = k
                else:
                    i += 1
            elif c == "<" and t.startswith("<<", i) and not t.startswith("<<<", i) and not t.startswith("<<=", i):
                j = i + 2
                strip = False
                if j < n and t[j] == "-":
                    strip = True
                    j += 1
                while j < n and t[j] in " \t":
                    j += 1
                m = re.match(r"""(?:'([^'\n]*)'|"([^"\n]*)"|\\?([A-Za-z0-9_.\-]+))""", t[j:j + 200])
                if m:
                    delim = m.group(1) or m.group(2) or m.group(3)
                    pending.append((delim, strip))
                    i = j + m.end()
                else:
                    i += 2
            elif c == "\n":
                i += 1
                if pending:
                    i = read_heredocs(i)
            elif c == "(" and term == ")":
                depth += 1
                i += 1
            elif c == ")" and term == ")":
                if depth == 0:
                    return i + 1
                depth -= 1
                i += 1
            else:
                i += 1
        return n

    scan_code(0, None)
    return out


def scan_make(t):
    """Makefile: non-recipe lines take the first unescaped '#'; recipe lines are shell."""
    out, pos = [], 0
    lines = t.split("\n")
    recipe_cont = False
    in_cont_comment = False
    for ln in lines:
        start = pos
        pos += len(ln) + 1
        if in_cont_comment:
            out.append((start, start + len(ln), "line"))
            in_cont_comment = ln.endswith("\\")
            continue
        is_recipe = ln.startswith("\t") or recipe_cont
        if is_recipe:
            spans = scan_sh(ln, base=start) if "#" in ln else []
            out.extend(spans)
            recipe_cont = ln.endswith("\\") and not spans
        else:
            recipe_cont = False
            i = 0
            while i < len(ln):
                if ln[i] == "\\":
                    i += 2
                    continue
                if ln[i] == "#":
                    out.append((start + i, start + len(ln), "line"))
                    in_cont_comment = ln.endswith("\\")
                    break
                i += 1
    return out


def scan_hash_lines(t):
    """Plain '#' line comments (udev rules, Dockerfile): only when '#' is the first non-blank char."""
    out, pos = [], 0
    for ln in t.split("\n"):
        s = ln.lstrip()
        if s.startswith("#"):
            off = len(ln) - len(s)
            out.append((pos + off, pos + len(ln), "line"))
        pos += len(ln) + 1
    return out


def scan_ps1(t):
    out, i, n = [], 0, len(t)
    while i < n:
        c = t[i]
        if c == "<" and t.startswith("<#", i):
            j = t.find("#>", i + 2)
            j = n if j < 0 else j + 2
            out.append((i, j, "block"))
            i = j
        elif c == "#":
            prev = t[i - 1] if i > 0 else "\n"
            if prev in " \t\n;({|&," or i == 0:
                k = t.find("\n", i)
                k = n if k < 0 else k
                out.append((i, k, "line"))
                i = k
            else:
                i += 1
        elif c == "@" and i + 1 < n and t[i + 1] in "\"'" and re.match(r"@[\"'][ \t]*\r?\n", t[i:i + 8]):
            q = t[i + 1]
            m = re.compile(r"\r?\n" + q + "@").search(t, i + 2)
            i = n if not m else m.end()
        elif c == '"':
            i += 1
            while i < n and t[i] != '"':
                i += 2 if t[i] == "`" else 1
            i += 1
        elif c == "'":
            i += 1
            while i < n:
                if t[i] == "'":
                    if i + 1 < n and t[i + 1] == "'":
                        i += 2
                        continue
                    break
                i += 1
            i += 1
        elif c == "`":
            i += 2
        else:
            i += 1
    return out


def scan_py(t):
    out = []
    lines = t.splitlines(keepends=True)
    offs = [0]
    for ln in lines:
        offs.append(offs[-1] + len(ln))
    try:
        for tok in tokenize.generate_tokens(io.StringIO(t).readline):
            if tok.type == tokenize.COMMENT:
                r, c = tok.start
                a = offs[r - 1] + c
                out.append((a, a + len(tok.string), "line"))
    except (tokenize.TokenError, IndentationError, SyntaxError) as e:
        raise RuntimeError("python tokenize failed: %s" % e)
    return out


def scan_js(t):
    out, i, n = [], 0, len(t)
    last = ""           # last significant char, to tell regex from division
    last_word = ""
    while i < n:
        c = t[i]
        if c == "/" and i + 1 < n and t[i + 1] == "*":
            j = t.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append((i, j, "block"))
            i = j
        elif c == "/" and i + 1 < n and t[i + 1] == "/":
            k = t.find("\n", i)
            k = n if k < 0 else k
            out.append((i, k, "line"))
            i = k
        elif c in "\"'":
            i += 1
            while i < n and t[i] != c and t[i] != "\n":
                i += 2 if t[i] == "\\" else 1
            i += 1
            last = "a"
        elif c == "`":
            i += 1
            depth = 0
            while i < n:
                if t[i] == "\\":
                    i += 2
                    continue
                if t.startswith("${", i):
                    depth += 1
                    i += 2
                    continue
                if t[i] == "}" and depth:
                    depth -= 1
                elif t[i] == "`" and depth == 0:
                    break
                i += 1
            i += 1
            last = "a"
        elif c == "/":
            if last in "(,=:[!&|?{};+-*%<>~^" or last == "" or last_word in ("return", "typeof", "case", "in", "of"):
                i += 1
                incls = False
                while i < n and t[i] != "\n":
                    if t[i] == "\\":
                        i += 2
                        continue
                    if t[i] == "[":
                        incls = True
                    elif t[i] == "]":
                        incls = False
                    elif t[i] == "/" and not incls:
                        break
                    i += 1
                i += 1
                while i < n and t[i].isalpha():
                    i += 1
                last = "a"
            else:
                i += 1
                last = "/"
        else:
            if not c.isspace():
                last = c
                if c.isalnum() or c in "_$":
                    j = i
                    while j < n and (t[j].isalnum() or t[j] in "_$"):
                        j += 1
                    last_word = t[i:j]
                    last = "a"
                    i = j
                    continue
                last_word = ""
            i += 1
    return out


def scan_xml(t):
    out, i = [], 0
    while True:
        a = t.find("<!--", i)
        if a < 0:
            return out
        b = t.find("-->", a + 4)
        b = len(t) if b < 0 else b + 3
        out.append((a, b, "block"))
        i = b


def scan_html(t):
    """HTML: <!-- --> comments, plus the contents of <script> (js) and <style> (css)."""
    out = []
    for a, b, k in scan_xml(t):
        out.append((a, b, k))
    mask = list(t)
    for a, b, _ in out:
        for x in range(a, b):
            mask[x] = " "
    ms = "".join(mask)
    for m in re.finditer(r"<script\b[^>]*>(.*?)</script>", ms, re.S | re.I):
        for a, b, k in scan_js(m.group(1)):
            out.append((m.start(1) + a, m.start(1) + b, k))
    for m in re.finditer(r"<style\b[^>]*>(.*?)</style>", ms, re.S | re.I):
        for a, b, k in scan_c(m.group(1), line_comments=False):
            out.append((m.start(1) + a, m.start(1) + b, k))
    return sorted(out)


# ----------------------------------------------------------------------------------------------

def classify(path, data):
    base = os.path.basename(path)
    ext = os.path.splitext(base)[1].lower()
    head = data[:200].decode("utf-8", "replace")
    if ext in (".c", ".h", ".cpp", ".inc"):
        return "c"
    if ext in (".ld", ".rc"):
        return "c_block" if ext == ".ld" else "c"
    if ext == ".s":
        return "c_block"
    if ext == ".css":
        return "c_block"
    if ext == ".js":
        return "js"
    if ext in (".html", ".htm"):
        return "html"
    if ext == ".manifest":
        return "xml"
    if ext == ".py":
        return "py"
    if ext == ".sh":
        return "sh"
    if ext == ".ps1":
        return "ps1"
    if base == "Makefile" or ext in (".mak", ".mk"):
        return "make"
    if base == "Dockerfile" or ext == ".rules":
        return "hash"
    if head.startswith("#!"):
        first = head.split("\n", 1)[0]
        if "python" in first:
            return "py"
        return "sh"
    return None


SCAN = {"c": scan_c, "c_block": lambda t: scan_c(t, line_comments=False), "js": scan_js, "html": scan_html,
        "xml": scan_xml, "py": scan_py, "sh": scan_sh, "ps1": scan_ps1, "make": scan_make, "hash": scan_hash_lines}


def decorate(kind_lang, raw):
    """Turn the raw comment source text into plain prose lines."""
    s = raw
    if s.startswith("/*"):
        s = s[2:]
        if s.endswith("*/"):
            s = s[:-2]
        lines = s.split("\n")
        res = []
        for k, ln in enumerate(lines):
            ln = ln.rstrip()
            if k == 0:
                ln = ln.lstrip("*").strip() if ln.strip().startswith("*") else ln.strip()
            else:
                ln = re.sub(r"^\s*\*(?!/)\s?", "", ln) if re.match(r"^\s*\*", ln) else ln
            res.append(ln)
        lines = res
    elif s.startswith("<!--"):
        s = s[4:]
        if s.endswith("-->"):
            s = s[:-3]
        lines = [ln.rstrip() for ln in s.split("\n")]
    elif s.startswith("<#"):
        s = s[2:]
        if s.endswith("#>"):
            s = s[:-2]
        lines = [ln.rstrip() for ln in s.split("\n")]
    else:
        lines = []
        for ln in s.split("\n"):
            ln = ln.rstrip().rstrip("\\") if False else ln.rstrip()
            ln = re.sub(r"^\s*(?://+|#+)\s?", "", ln)
            lines.append(ln)
    # common indentation + trim blank edges
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    ind = [len(x) - len(x.lstrip()) for x in lines if x.strip()]
    cut = min(ind) if ind else 0
    lines = [x[cut:] if x.strip() else "" for x in lines]
    return lines


def keep_comment(raw, lineno, lang):
    body = raw
    if LEGAL.search(body):
        return True
    txt = "\n".join(decorate(lang, raw)).strip()
    if lineno == 1 and raw.startswith("#!"):
        return True
    if lineno <= 2 and re.match(r"#\s*(?:-\*-|vim:|coding[:=])", raw):
        return True
    if DIRECTIVE.match(txt):
        return True
    return False


def _pre_rmguard(text):
    out, lit = [], False
    for ln in text.split("\n"):
        if "static const char RMGUARD_SCRIPT[] =" in ln:
            lit = True
        elif lit:
            m = re.match(r'^    "(.*)\\n"$', ln)
            if not m:
                lit = False
            elif m.group(1).startswith("#") and not m.group(1).startswith("#!"):
                continue
        out.append(ln)
    return "\n".join(out)


def _pre_cli(text):
    return text.replace("        # NUL disables all pip config files on Windows, including global/site config.\n", "")


PRE = {"ui/rmguard.c": _pre_rmguard, "tests/test_windows_cli.py": _pre_cli}


def process(path, data, lang):
    text = data.decode("utf-8")
    if path in PRE:
        text = PRE[path](text)
    crlf = "\r\n" in text
    if crlf:
        text = text.replace("\r\n", "\n")
    assert S0 not in text and S1 not in text
    spans = SCAN[lang](text)
    spans = [s for s in sorted(spans)]
    comments = []        # (id, lines, kind, trailing)
    kept = []
    pieces, last = [], 0
    for a, b, kind in spans:
        raw = text[a:b]
        lineno = text.count("\n", 0, a) + 1
        if keep_comment(raw, lineno, lang):
            kept.append((lineno, raw.split("\n", 1)[0][:100]))
            continue
        cid = len(comments)
        before = text[last:a]
        pieces.append(before)
        ls = text.rfind("\n", 0, a) + 1
        le = text.find("\n", b)
        le = len(text) if le < 0 else le
        full_line = text[ls:a].strip() == "" and text[b:le].strip() == ""
        comments.append((cid, decorate(lang, raw), kind, not full_line))
        # glue rule: avoid welding two tokens together when a mid-line block comment disappears
        pieces.append(S0 + str(cid) + S1)
        last = b
    pieces.append(text[last:])
    work = "".join(pieces)

    # line pass
    src = work.split("\n")
    outl = []                 # (text, [cids])
    pend = []                 # cids waiting for the next kept line
    removed_run_blank_before = None
    kept_lines = []
    for ln in src:
        ids = [int(x) for x in SENT.findall(ln)]
        bare = SENT.sub("", ln)
        if ids and bare.strip() == "" or (ids and bare.strip() == "\\" and False):
            pend.extend(ids)
            kept_lines.append(None)       # removed whole line
            continue
        if ids:
            # glue: whitespace on both sides collapses to one, none needed if one side is punctuation
            def glue(m_before, m_after):
                return m_before, m_after
            new = ln
            # strip trailing comment + the whitespace before it
            new = re.sub(r"[ \t]*" + S0 + r"\d+" + S1 + r"[ \t]*$", "", new)
            # mid-line comments: if neighbours are both word chars keep one space, else squeeze surrounding space
            def mid(m):
                a = m.string[:m.start()]
                b = m.string[m.end():]
                la = a[-1:] if a else ""
                fb = b[:1] if b else ""
                if (la.isspace() or la == "") and (fb.isspace() or fb == ""):
                    return "" if la == "" or fb == "" else ""
                if la.isspace() or fb.isspace():
                    return ""
                if (la.isalnum() or la in "_") and (fb.isalnum() or fb in "_"):
                    return " "
                return ""
            while True:
                m = SENT.search(new)
                if not m:
                    break
                rep = mid(m)
                new = new[:m.start()] + rep + new[m.end():]
                # squeeze double space left behind
                if rep == "" and m.start() > 0 and m.start() < len(new) and new[m.start() - 1] == " " and new[m.start()] == " ":
                    new = new[:m.start()] + new[m.start() + 1:]
            outl.append([new, ids + pend])
            pend = []
            kept_lines.append(new)
        else:
            outl.append([ln, pend])
            pend = []
            kept_lines.append(ln)
    # trailing pending (comment at EOF): anchor to last line
    tail_ids = pend

    # blank-line tidy around removed regions: build final list tracking where removals happened
    final = []                 # [text, cids]
    removed_before = False
    idx = 0
    for ln, ids in outl:
        final.append([ln, list(ids)])
    # collapse: where a removal created "blank,(removed),blank" or "{ ,(removed),blank" or start-of-file blank
    res = []
    i = 0
    changed = [bool(ids) for _, ids in final]
    # a line "owns" removal if it has ids attached (comments were removed just before it) -- only then tidy
    while i < len(final):
        ln, ids = final[i]
        if ids and ln.strip() == "":
            prev = res[-1][0] if res else None
            if prev is None or prev.strip() == "" or re.search(r"[{(\[]\s*$", prev):
                # drop this blank line, hand its anchors to the next kept line
                if i + 1 < len(final):
                    final[i + 1][1] = ids + final[i + 1][1]
                else:
                    tail_ids = ids + tail_ids
                i += 1
                continue
        res.append([ln, ids])
        i += 1
    # a blank line right before a closing brace that follows a removal
    out_lines, anchors = [], []
    for ln, ids in res:
        out_lines.append(ln)
        anchors.append(ids)
    # also: blank line directly after removed lines but preceded by blank (handled), and file leading blanks
    while out_lines and out_lines[0].strip() == "" and anchors[0]:
        a = anchors.pop(0)
        out_lines.pop(0)
        if anchors:
            anchors[0] = a + anchors[0]
        else:
            tail_ids = a + tail_ids
    # trailing blank at EOF created by removal
    new_text = "\n".join(out_lines)
    if crlf:
        new_text = new_text.replace("\n", "\r\n")

    entries = []
    for k, ids in enumerate(anchors):
        for cid in ids:
            cm = comments[cid]
            entries.append((k + 1, out_lines[k].strip(), cm))
    for cid in tail_ids:
        entries.append((max(len(out_lines), 1), "(end of file)", comments[cid]))
    entries.sort(key=lambda e: (e[0], e[2][0]))
    return new_text, entries, kept


def fence(txt):
    f = "~~~"
    while f in txt:
        f += "~"
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--list", required=True)
    ap.add_argument("--md", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--survey", action="store_true")
    ap.add_argument("--only", help="regex on path")
    a = ap.parse_args()
    root = a.root
    files = [l.strip() for l in open(a.list) if l.strip()]
    report, skipped, totals = [], [], {}
    kept_all = []
    ncom = 0
    for rel in files:
        if a.only and not re.search(a.only, rel):
            continue
        p = os.path.join(root, rel)
        if os.path.islink(p) or not os.path.isfile(p):
            skipped.append((rel, "not a regular file"))
            continue
        data = open(p, "rb").read()
        if is_binary(data):
            skipped.append((rel, "binary"))
            continue
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            skipped.append((rel, "not utf-8"))
            continue
        head = data[:1500].decode("utf-8", "replace")
        if rel in THIRD_PARTY or (not rel.endswith(".py") and re.search(r"GENERATED by|DO NOT EDIT|lv_font_conv|^\s*\*\s*Bpp:", head, re.M)):
            skipped.append((rel, "generated or vendored"))
            continue
        lang = classify(rel, data)
        if lang is None:
            skipped.append((rel, "not source (no comment syntax known)"))
            continue
        try:
            new, entries, kept = process(rel, data, lang)
        except Exception as e:      # noqa
            skipped.append((rel, "error: %s" % e))
            continue
        totals[lang] = totals.get(lang, 0) + 1
        if kept:
            kept_all.append((rel, kept))
        if entries:
            report.append((rel, lang, entries, len(data.decode().split("\n")), len(new.split("\n"))))
            ncom += len(entries)
        if a.apply and new.encode() != data:
            open(p, "wb").write(new.encode())
    # markdown
    with open(a.md, "w") as f:
        f.write("# Comments moved out of the source\n\n")
        f.write("The source tree carries no comments (see `agents/AGENTS.md`, rule *No comments in source*). "
                "What the comments used to say is kept here, file by file, so the knowledge is not lost.\n\n")
        f.write("How to read an entry: **L<n>** is the line in the stripped file that the comment sat on or just above, "
                "followed by that line's code (trimmed) so the anchor survives later edits. "
                "A comment that trailed code on the same line is marked *(trailing)*.\n\n")
        f.write("Kept in the source on purpose: shebangs, coding cookies, SPDX / copyright / licence notices, and tool "
                "directives (`noqa`, `NOLINT`, fallthrough markers, Dockerfile parser directives).\n\n")
        f.write("Not touched: vendored or third-party code (`ui/lvgl`, `ui/third_party`, `src/usbboot`, `spl-src`, "
                "`corresponding-source`, `licenses`, `ui/sqlite3.[ch]`, `ui/jsmn.h`, `ui/md5.c`, `ui/lv_conf.h`, "
                "`ui/tools/stb_image.h`), generated files (`ui/font_*.c`, `ui/i18n_tables.c`, `ui/theme_presets.inc`, "
                "`ui/theme_fonts.h`: their generators in `ui/tools/` are stripped, the outputs are not), binaries, "
                "Markdown/text docs, and config/data files (`.gitignore`, YAML, JSON, lock files).\n\n")
        f.write("## Index\n\n| File | Comments |\n|---|---|\n")
        for rel, lang, ents, _, _ in report:
            f.write("| [%s](#%s) | %d |\n" % (rel, re.sub(r"[^a-z0-9\- ]", "", rel.lower()).replace(" ", "-"), len(ents)))
        f.write("\n")
        for rel, lang, ents, _, _ in report:
            f.write("## %s\n\n" % rel)
            for line, code, (cid, lines, kind, trailing) in ents:
                code_s = code if len(code) <= 100 else code[:97] + "..."
                code_s = code_s.replace("`", "'")
                f.write("**L%d** `%s`%s\n\n" % (line, code_s, " *(trailing)*" if trailing else ""))
                body = "\n".join(lines)
                fn = fence(body)
                f.write("%stext\n%s\n%s\n\n" % (fn, body, fn))
    print("files by language:", totals)
    print("files with comments:", len(report), "comments:", ncom)
    for rel, why in skipped:
        print("SKIP", rel, "-", why)
    for rel, kept in kept_all:
        for ln, first in kept:
            print("KEEP", "%s:%d" % (rel, ln), first)


if __name__ == "__main__":
    main()
