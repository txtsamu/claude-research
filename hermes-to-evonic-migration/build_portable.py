#!/usr/bin/env python3
"""Build one portable Evonic agent file (schema evonic.agent v1) per Hermes profile.

Run as root on the host that holds ~/.hermes. Output (mode 0600, it holds credentials copied as is by the user's choice):
  <out>/hermes_default.json, hermes_dev.json, ... , plus build-report.json

  default profile  -> hermes_default  (the one that owns the Telegram bot; routes to the specialists)
  profiles/<name>  -> hermes_<name>   (system prompt = that profile's SOUL.md; KB = that profile's memories + skills)

Usage: build_portable.py --out /srv/migrate/portable [--model deepseek-v4.1-flash] [--include-archive]
"""
import argparse, json, os, re, sys, tempfile, shutil
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hermes_to_evonic_kb as c

HERMES = "/root/.hermes"
TOOLS = ["bash", "read_file", "write_file", "str_replace", "patch"]
NOTE = ("\n\n---\nYou now run on Evonic. The other members of your team are Evonic agents named hermes_<role>; "
        "message them with the agent messaging tools. Notes imported from the old Hermes setup are in your knowledge base "
        "(hermes-memory = what Hermes remembered, hermes-skills = its runbooks). Read the relevant ones before acting; "
        "they may mention Hermes-only tools (MCP servers, kanban, delegate_task) that you do not have.\n")


def profile_description(path, fallback):
    try:
        t = open(path, encoding="utf-8").read()
    except OSError:
        return fallback
    m = re.search(r"^description:\s*(.*?)(?=^\w[\w_]*:|\Z)", t, re.S | re.M)
    if not m:
        return fallback
    v = re.sub(r"\s+", " ", m.group(1).strip())
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1].replace("''", "'")
    return v or fallback


def kb_files(hermes_dir, label, include_archive):
    """Run the converter into a temp dir and read the markdown back as {path, content}."""
    c.PROFILE = label
    stats = Counter()
    tmp = tempfile.mkdtemp(prefix="h2e-")
    try:
        c.migrate_memories(hermes_dir, tmp, False, stats)
        c.migrate_skills(hermes_dir, tmp, include_archive, False, stats)
        files = []
        for dp, _, fn in os.walk(tmp):
            for f in sorted(fn):
                p = os.path.join(dp, f)
                files.append({"path": os.path.relpath(p, tmp).replace(os.sep, "/"), "content": open(p, encoding="utf-8").read()})
        files.sort(key=lambda x: x["path"])
        return files, stats
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="deepseek-v4.1-flash")
    ap.add_argument("--include-archive", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, mode=0o700, exist_ok=True)
    os.chmod(a.out, 0o700)

    profs = sorted(p for p in os.listdir(f"{HERMES}/profiles") if os.path.isdir(f"{HERMES}/profiles/{p}") and not p.startswith("."))
    team = ["default"] + profs
    ids = {p: f"hermes_{p}" for p in team}
    descs = {p: profile_description(f"{HERMES}/profiles/{p}/profile.yaml", p) for p in profs}
    descs["default"] = "Default assistant of the former Hermes team: talks to the user on Telegram and hands specialist work to the team."
    report = {}

    for p in team:
        hdir = HERMES if p == "default" else f"{HERMES}/profiles/{p}"
        if p == "default":
            roster = "\n".join(f"- {ids[q]}: {descs[q]}" for q in profs)
            prompt = ("You are the default assistant of a team of specialist agents (formerly the Hermes team), now running on Evonic. "
                      "You are the one the user talks to on Telegram. Answer simple things yourself. For specialist work, message the "
                      "right teammate with the agent messaging tools and relay the result, keeping answers short.\n\nYour team:\n"
                      f"{roster}\n\nThe knowledge base holds what Hermes remembered about the user and the homelab (hermes-memory) and its "
                      "runbooks (hermes-skills). Read the relevant notes before acting; they may mention Hermes-only tools "
                      "(MCP servers, kanban, delegate_task) that you do not have.")
        else:
            soul = open(f"{hdir}/SOUL.md", encoding="utf-8").read().strip() if os.path.isfile(f"{hdir}/SOUL.md") else ""
            prompt = (soul or f"You are the {p} specialist.") + NOTE
        files, st = kb_files(hdir, None if p == "default" else p, a.include_archive)
        others = [ids[q] for q in team if q != p]
        payload = {
            "schema": "evonic.agent", "version": 1,
            "metadata": {"omitted_secret_variable_keys": []},
            "agent": {
                "name": "Hermes " + ("default" if p == "default" else p),
                "description": descs[p][:1900],
                "system_prompt": prompt[:100000],
                "configuration": {
                    "model_id": a.model, "sandbox_enabled": 0, "agent_messaging_enabled": 1,
                    "messaging_acl": json.dumps(others), "messaging_acl_mode": "whitelist", "enabled": 1,
                },
                "tools": TOOLS, "skills": [], "variables": [], "knowledge_base": files,
            },
        }
        path = os.path.join(a.out, ids[p] + ".json")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        report[ids[p]] = {"kb_files": len(files), "memory_docs": st["memory_docs"], "skill_docs": st["skill_docs"],
                          "skipped_archive": st["skipped_archive"], "prompt_chars": len(prompt), "bytes": os.path.getsize(path)}
    json.dump(report, open(os.path.join(a.out, "build-report.json"), "w"), indent=1)
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
