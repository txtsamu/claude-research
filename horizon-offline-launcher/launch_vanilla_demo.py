"""Launch official 26.3 client in DEMO mode (no account) with the manifest's default JVM args."""
import json, os, subprocess, sys
MC = os.path.expanduser("~/.minecraft"); HERE = os.getcwd()
V = json.load(open("26.3.json"))
def ok(l):
    r = l.get("rules")
    if not r: return True
    a = False
    for x in r:
        if x.get("os", {}).get("name") in (None, "linux"): a = x["action"] == "allow"
    return a
cp = [f"{MC}/libraries/{l['downloads']['artifact']['path']}" for l in V["libraries"]
      if ok(l) and "artifact" in l.get("downloads", {}) and not any(s in l["downloads"]["artifact"]["path"] for s in ("arm64", "aarch64", "riscv", "ppc"))]
cp.append(f"{MC}/versions/26.3/26.3.jar")
jvm = ["-Xms2G", "-Xmx4G", "-XX:+UseCompactObjectHeaders", "-XX:+AlwaysPreTouch", "-XX:+UseStringDeduplication", "-XX:+UseZGC",
       "-XX:StackShadowPages=32", "--enable-native-access=ALL-UNNAMED", "--add-exports", "java.base/jdk.internal.misc=ALL-UNNAMED",
       f"-Djava.library.path={HERE}/natives/java", f"-Djna.tmpdir={HERE}/natives/jna",
       f"-Dorg.lwjgl.system.SharedLibraryExtractPath={HERE}/natives/lwjgl", f"-Dio.netty.native.workdir={HERE}/natives/netty",
       "-Dminecraft.launcher.brand=measure", "-Dminecraft.launcher.version=1", "-cp", ":".join(cp)]
game = ["--username", "Measure", "--version", "26.3", "--gameDir", f"{HERE}/vanilla-gamedir", "--assetsDir", f"{MC}/assets",
        "--assetIndex", V["assetIndex"]["id"], "--uuid", "00000000-0000-0000-0000-000000000000", "--accessToken", "0",
        "--versionType", "release", "--demo"]
os.execvp("java", ["java"] + jvm + [V["mainClass"]] + game)
