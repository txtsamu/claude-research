"""Validate the benchmark: for each task an untouched fixture must FAIL and the reference solution must PASS."""
import sys, tempfile, shutil
from pathlib import Path
import tasks

bad = 0
for t in tasks.TASKS:
    with tempfile.TemporaryDirectory() as td:
        w1 = Path(td, "empty"); t.setup(w1)
        try: ok0, d0 = t.check(w1, "")
        except Exception as e: ok0, d0 = False, f"checker raised {type(e).__name__}: {e}"
        w2 = Path(td, "solved"); t.setup(w2); t.solve(w2)
        try: ok1, d1 = t.check(w2, "")
        except Exception as e: ok1, d1 = False, f"checker raised {type(e).__name__}: {e}"
        # prompt must format cleanly
        try: t.prompt.format(workdir="/x")
        except Exception as e: ok1, d1 = False, f"prompt format error {e}"
        good = (not ok0) and ok1
        bad += (not good)
        print(f"{'OK  ' if good else 'FAIL'} {t.id:24s} untouched->{'pass' if ok0 else 'fail'} ({d0[:45]})  solved->{'pass' if ok1 else 'fail'} ({d1[:60]})")
print(f"\n{len(tasks.TASKS)} tasks, {bad} broken")
sys.exit(1 if bad else 0)
