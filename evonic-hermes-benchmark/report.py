#!/usr/bin/env python3
"""Summarise results.jsonl into markdown tables (stdlib only)."""
import json, math, statistics as st, sys, collections

def wilson(k, n, z=1.96):
    if n == 0: return (0.0, 0.0)
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0, c - h), min(1, c + h))

def med(x): x = [v for v in x if v is not None]; return st.median(x) if x else None
def mean(x): x = [v for v in x if v is not None]; return sum(x) / len(x) if x else None
def fmt(v, nd=1): return "n/a" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))

allrows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
rows = [r for r in allrows if not r.get("invalid")]
invalid = collections.Counter(r["agent"] for r in allrows if r.get("invalid"))
retried = collections.Counter(r["agent"] for r in allrows if r.get("infra_failures"))
agents = sorted({r["agent"] for r in rows})
by = collections.defaultdict(list)
for r in rows: by[r["agent"]].append(r)

print("## Overall (invalid runs, where the provider failed on every attempt, are excluded)\n")
print("| agent | runs | pass rate (95% CI) | median wall s | mean tool calls | mean tokens in | mean tokens out | errors | invalid | runs needing a retry |")
print("|---|---|---|---|---|---|---|---|---|---|")
for a in agents:
    rs = by[a]; k = sum(r["passed"] for r in rs); lo, hi = wilson(k, len(rs))
    print(f"| {a} | {len(rs)} | {k}/{len(rs)} = {100*k/len(rs):.0f}% ({100*lo:.0f}-{100*hi:.0f}%) | {fmt(med([r['wall_seconds'] for r in rs]))} | "
          f"{fmt(mean([r['tool_calls'] for r in rs]))} | {fmt(mean([r['tokens_in'] for r in rs]),0)} | {fmt(mean([r['tokens_out'] for r in rs]),0)} | {sum(1 for r in rs if r.get('error'))} | {invalid[a]} | {retried[a]} |")

print("\n## By category (pass rate, median wall s)\n")
cats = sorted({r["category"] for r in rows})
print("| category | " + " | ".join(agents) + " |"); print("|---|" + "---|" * len(agents))
for c in cats:
    cells = []
    for a in agents:
        rs = [r for r in by[a] if r["category"] == c]
        cells.append(f"{sum(r['passed'] for r in rs)}/{len(rs)} ({fmt(med([r['wall_seconds'] for r in rs]),0)}s)" if rs else "-")
    print(f"| {c} | " + " | ".join(cells) + " |")

print("\n## By task (passes / reps)\n")
tasks = sorted({r["task"] for r in rows})
print("| task | " + " | ".join(agents) + " |"); print("|---|" + "---|" * len(agents))
wins = collections.Counter()
for t in tasks:
    cells = []; rate = {}
    for a in agents:
        rs = [r for r in by[a] if r["task"] == t]
        k = sum(r["passed"] for r in rs); cells.append(f"{k}/{len(rs)}"); rate[a] = k / len(rs) if rs else None
    print(f"| {t} | " + " | ".join(cells) + " |")
    if len(agents) == 2 and None not in rate.values():
        x, y = agents
        wins[x if rate[x] > rate[y] else y if rate[y] > rate[x] else "tie"] += 1
if len(agents) == 2:
    x, y = agents; n = wins[x] + wins[y]
    # two-sided exact sign test over tasks where pass rates differ
    p = min(1.0, 2 * sum(math.comb(n, i) for i in range(0, min(wins[x], wins[y]) + 1)) / 2 ** n) if n else 1.0
    print(f"\nTasks won: {x}={wins[x]}, {y}={wins[y]}, tied={wins['tie']}. Sign test over differing tasks: p={p:.3f} (n={n}).")

print("\n## Failures (first detail per task/agent)\n")
seen = set()
for r in rows:
    if not r["passed"] and (r["agent"], r["task"]) not in seen:
        seen.add((r["agent"], r["task"])); print(f"- {r['agent']} {r['task']} r{r['rep']}: {r['detail'][:140]}" + (f" | error: {str(r['error'])[:100]}" if r.get("error") else ""))
