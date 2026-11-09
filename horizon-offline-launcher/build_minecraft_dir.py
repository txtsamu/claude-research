"""Build a ~/.minecraft layout for 26.3 from Mojang's public manifest + the user's jars."""
import json, hashlib, os, shutil, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
MC = os.path.expanduser("~/.minecraft")
V = json.load(open("26.3.json"))
DL = os.path.expanduser("~/Downloads")

def sha1(p):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()

def fetch(url, dest, want):
    if os.path.exists(dest) and (not want or sha1(dest) == want): return
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    for _ in range(3):
        try:
            urllib.request.urlretrieve(url, dest + ".part")
            if want and sha1(dest + ".part") != want: continue
            os.replace(dest + ".part", dest); return
        except Exception as e: err = e
    print("FAILED", url, file=sys.stderr)

def allowed(lib):
    r = lib.get("rules")
    if not r: return True
    ok = False
    for x in r:
        os_ = x.get("os", {}).get("name")
        if os_ in (None, "linux"): ok = x["action"] == "allow"
    return ok

# version json + client jar (user's own download, checksum already verified == manifest)
vd = f"{MC}/versions/26.3"; os.makedirs(vd, exist_ok=True)
shutil.copy("26.3.json", f"{vd}/26.3.json")
if not os.path.exists(f"{vd}/26.3.jar"): shutil.copy(f"{DL}/client.jar", f"{vd}/26.3.jar")
jobs = []
for lib in V["libraries"]:
    if not allowed(lib): continue
    a = lib.get("downloads", {}).get("artifact")
    if a: jobs.append((a["url"], f"{MC}/libraries/{a['path']}", a["sha1"]))
ai = V["assetIndex"]
idx = f"{MC}/assets/indexes/{ai['id']}.json"
fetch(ai["url"], idx, ai["sha1"])
for h in {o["hash"] for o in json.load(open(idx))["objects"].values()}:
    jobs.append((f"https://resources.download.minecraft.net/{h[:2]}/{h}", f"{MC}/assets/objects/{h[:2]}/{h}", h))
print(len(jobs), "files")
with ThreadPoolExecutor(16) as ex: list(ex.map(lambda j: fetch(*j), jobs))
print("done")
