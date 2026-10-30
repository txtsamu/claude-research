"""Find test string literals that matched text in a file at HEAD but no longer match it after the strip."""
import ast, glob, os, subprocess, sys
root = os.path.abspath(sys.argv[1])
changed = subprocess.run(["/usr/bin/git", "-C", root, "diff", "--name-only"], capture_output=True, text=True).stdout.split()
old, new = {}, {}
for rel in changed:
    p = os.path.join(root, rel)
    if not os.path.isfile(p):
        continue
    try:
        o = subprocess.run(["/usr/bin/git", "-C", root, "show", "HEAD:" + rel], capture_output=True).stdout.decode()
        n = open(p, encoding="utf-8").read()
    except Exception:
        continue
    old[rel], new[rel] = o, n
tests = glob.glob(root + "/tests/*.py") + glob.glob(root + "/ui/tests/*.py") + glob.glob(root + "/build/*.py") + glob.glob(root + "/diskos_installer/*.py")
seen = set()
for tp in tests:
    try:
        tree = ast.parse(open(tp, encoding="utf-8").read())
    except Exception:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) >= 14:
            lit = node.value
            for rel in old:
                if rel == os.path.relpath(tp, root):
                    continue
                if lit in old[rel] and not any(lit in v for v in new.values()):
                    key = (os.path.relpath(tp, root), node.lineno, rel)
                    if key not in seen:
                        seen.add(key)
                        print("%s:%d  literal no longer in %s: %r" % (key[0], key[1], rel, lit[:90]))
