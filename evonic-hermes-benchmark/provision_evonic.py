"""Run as root on home. Creates the bench agent and applies the lean benchmark config. Never prints the key/password."""
import os, re, secrets, subprocess, pwd
v = None
for l in open("/root/.hermes/.env"):
    m = re.match(r"^OPENCODE_GO_API_KEY=(.*)$", l.strip())
    if m:
        v = m.group(1).strip().strip('"').strip("'")
assert v, "key not found"
pw = secrets.token_urlsafe(18)
p = "/srv/bench/evonic_password"
open(p, "w").write(pw)
u = pwd.getpwnam("moo"); os.chown(p, u.pw_uid, u.pw_gid); os.chmod(p, 0o600)
env = dict(os.environ, HOME="/var/lib/evonic", BENCH_KEY=v, ADMIN_PW=pw)

def ru(*cmd, check=True):
    r = subprocess.run(["runuser", "-u", "evonic", "--", *cmd], cwd="/opt/evonic-source", env=env,
                       stdin=subprocess.DEVNULL, capture_output=True, text=True)
    out = (r.stdout + r.stderr).replace(v, "<key>").replace(pw, "<pw>")
    label = " ".join(cmd[:3])
    print(f"$ {label} -> rc={r.returncode}")
    print("\n".join(out.strip().splitlines()[-6:]))
    if check and r.returncode:
        raise SystemExit(1)

ru("./evonic", "agent", "add", "bench", "--name", "Bench Agent", "--description", "Benchmark agent",
   "--model", "openrouter/openai/gpt-4o-mini", check=False)
ru("/opt/evonic-venv/bin/python", "/srv/bench/code/evonic_home_setup.py")
