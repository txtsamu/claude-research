#!/usr/bin/env python3
"""Run the task suite against one or more agents, append results to a JSONL file.

  python3 bench.py --agents hermes,evonic --reps 3 --out /srv/bench/results/run1.jsonl
  python3 bench.py --agents hermes --tasks A1_create_files,B2_fix_bug --reps 1 --out /tmp/x.jsonl
  python3 bench.py --dry-run ...

Order is randomised per (rep, task) and the agents are interleaved, so API latency drift and time of day
do not systematically favour one agent. Re-running with the same --out resumes (finished runs are skipped).
"""
import argparse, importlib, json, os, random, re, shutil, sys, time, traceback
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tasks as T

WORKROOT = Path(os.environ.get("BENCH_WORKROOT", "/srv/bench/work"))
MAX_ATTEMPTS = int(os.environ.get("BENCH_MAX_ATTEMPTS", "5"))
BACKOFF_S = int(os.environ.get("BENCH_BACKOFF_S", "45"))
# Provider/infrastructure failures are not the agent's fault: retry the whole run from a clean fixture, identically for
# every agent. A run that never completes is recorded invalid and excluded from pass rates (counted in the report).
INFRA = re.compile(r"overloaded|HTTP 429|HTTP 5\d\d|rate limit|temporarily unavailable|bad gateway|service unavailable|"
                   r"connection (reset|aborted|refused)|read timed out|upstream request failed", re.I)


def is_infra_failure(res):
    if not res.get("error"):
        return False
    return bool(INFRA.search(f"{res.get('error')} {res.get('final_text') or ''}"))


def load_driver(name):
    if name == "hermes":
        import hermes_driver as d
        return d
    if name == "evonic":
        import evonic_adapter as d
        return d
    raise SystemExit(f"unknown agent {name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agents", default="hermes,evonic")
    ap.add_argument("--tasks", default="all")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=20261106)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep-workdirs", action="store_true")
    a = ap.parse_args()

    agents = a.agents.split(",")
    sel = T.TASKS if a.tasks == "all" else [T.BY_ID[i] for i in a.tasks.split(",")]
    rnd = random.Random(a.seed)
    plan = []
    for rep in range(a.reps):
        order = list(sel); rnd.shuffle(order)
        for t in order:
            ag = list(agents); rnd.shuffle(ag)
            for g in ag:
                plan.append((rep, t, g))

    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        for l in out.read_text().splitlines():
            try:
                r = json.loads(l); done.add((r["agent"], r["task"], r["rep"]))
            except Exception:
                pass
    todo = [(r, t, g) for r, t, g in plan if (g, t.id, r) not in done]
    print(f"{len(plan)} runs planned, {len(plan) - len(todo)} already done, {len(todo)} to go", flush=True)
    if a.dry_run:
        for r, t, g in todo: print(f"  rep{r} {t.id:24s} {g}")
        return

    drivers = {g: load_driver(g) for g in agents}
    if "hermes" in drivers:
        drivers["hermes"].prepare_key()
    n = 0
    try:
        for rep, t, g in todo:
            n += 1
            w = WORKROOT / g / t.id / f"r{rep}"
            shutil.rmtree(w, ignore_errors=True)
            w.mkdir(parents=True, exist_ok=True); t.setup(w)
            prompt = t.prompt.format(workdir=str(w))
            res, attempts, infra = None, 0, 0
            while attempts < MAX_ATTEMPTS:
                attempts += 1
                if attempts > 1:
                    shutil.rmtree(w, ignore_errors=True); w.mkdir(parents=True, exist_ok=True); t.setup(w)
                t0 = time.time()
                try:
                    res = drivers[g].run_task(prompt, str(w), t.timeout_s)
                except Exception as e:
                    res = {"final_text": "", "wall_seconds": round(time.time() - t0, 2), "tool_calls": 0, "turns": None,
                           "tokens_in": None, "tokens_out": None, "error": f"driver exception: {e}\n{traceback.format_exc()[-400:]}"}
                if not is_infra_failure(res):
                    break
                infra += 1
                print(f"    infra failure on attempt {attempts} ({g} {t.id}): {(res.get('error') or '')[:90].strip()!r}; backing off", flush=True)
                if attempts < MAX_ATTEMPTS:
                    time.sleep(BACKOFF_S * attempts)
            invalid = is_infra_failure(res)
            try:
                ok, detail = t.check(w, res.get("final_text", ""))
            except Exception as e:
                ok, detail = False, f"checker raised {type(e).__name__}: {e}"
            if invalid:
                ok, detail = False, "INVALID: provider failure on every attempt"
            rec = {"agent": g, "attempts": attempts, "infra_failures": infra, "invalid": invalid, "task": t.id, "category": t.category, "rep": rep, "passed": bool(ok), "detail": detail[:300],
                   "wall_seconds": res.get("wall_seconds"), "tool_calls": res.get("tool_calls"), "turns": res.get("turns"),
                   "tokens_in": res.get("tokens_in"), "tokens_out": res.get("tokens_out"), "error": res.get("error"),
                   "final_text": (res.get("final_text") or "")[:500], "ts": int(time.time())}
            with open(out, "a") as f: f.write(json.dumps(rec) + "\n")
            print(f"[{n}/{len(todo)}] {g:7s} {t.id:24s} r{rep} {'PASS' if ok else 'FAIL'} {rec['wall_seconds']}s "
                  f"tools={rec['tool_calls']} tok={rec['tokens_in']}/{rec['tokens_out']} {'' if ok else detail[:80]}", flush=True)
            if not a.keep_workdirs and ok:
                shutil.rmtree(w, ignore_errors=True)
    finally:
        if "hermes" in drivers:
            drivers["hermes"].cleanup_key()


if __name__ == "__main__":
    main()
