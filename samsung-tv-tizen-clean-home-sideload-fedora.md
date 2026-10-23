---
type: how-to
tags: [samsung, tizen, tv, sideload, sdb, tizen-studio, fedora, clean-home]
created: 2026-10-23
last_verified: 2026-10-23
status: current
---

# Sideloading Clean Home on a 2020 Samsung Tizen TV from Fedora

Goal: follow `DavidNgugi/samsung-tv-unlock` ("Clean Home" launcher) on a Samsung UA43T6500 (2020, `20_KANTS2_FHD`, Tizen 5.5). Note the repo is **not a root guide**: its table lists root as "No" for Tizen 6.0 and "Unknown" for Tizen 4/5; real root (`samsung-tv-root`) only covers Tizen 6.5+. Tizen 5.5 is not an officially supported row, but the web-app install worked. Part 2 of the repo (Home-button / boot vconf rewrite) was **not** attempted: `sdb shell id` returns nothing on this TV, so there is no readable baseline to restore.

## 1. Find the TV and confirm it is reachable

```bash
nmap -n -p 8001,8002,8080,26101,9197 --open 192.168.50.0/24
# 192.168.50.31 had 8001/8002/26101 open
curl -s http://192.168.50.31:8001/api/v2/   # model, developerMode, developerIP, DUID
```

`modelName` = `UA43T6500AKXXD`, `model` = `20_KANTS2_FHD` (2020 => Tizen 5.5). `developerMode:"1"` and `developerIP` = this PC were already set, so TV-side Developer Mode (Apps -> 12345 -> On, Host PC IP) was already done. The API JSON contains raw control characters; strip them or regex fields rather than `json.load`.

## 2. Install the Tizen CLI on Fedora (the installer is Ubuntu-only)

```bash
mkdir -p ~/tizen-dl && cd ~/tizen-dl
curl -sSfLO https://download.tizen.org/sdk/Installer/tizen-studio_6.1/web-cli_Tizen_Studio_6.1_ubuntu-64.bin   # ~280 MB
chmod +x web-cli_Tizen_Studio_6.1_ubuntu-64.bin
./web-cli_Tizen_Studio_6.1_ubuntu-64.bin --accept-license ~/tizen-studio
```

It refuses: `you must install "expect" "libgnome" "qemu-user" "webkitgtk" "libpng12"`. Those are IDE-only dependencies (and libgnome/libpng12 don't exist on Fedora 43). The check is a shell snippet at the top of the .bin. Patch a **same-length** copy so archive offsets/md5 stay valid:

```bash
python3 -I - <<'PY'
b=open('web-cli_Tizen_Studio_6.1_ubuntu-64.bin','rb').read()
old=b'if [ -n "$pkg_list" ] ; then'
new=b'if [ -n ""          ] ; then'
assert len(old)==len(new) and b.count(old)==1
open('web-cli-patched.bin','wb').write(b.replace(old,new))
PY
chmod +x web-cli-patched.bin
```

Second failure: the bundled `unzip` needs `libbz2.so.1.0` (Fedora only ships `.so.1`). Shim it:

```bash
mkdir -p ~/tizen-dl/shim && ln -sf /usr/lib64/libbz2.so.1 ~/tizen-dl/shim/libbz2.so.1.0
export LD_LIBRARY_PATH=$HOME/tizen-dl/shim
./web-cli-patched.bin --accept-license ~/tizen-studio
```

Keep `LD_LIBRARY_PATH` set for the next steps too.

## 3. Install the TV + certificate extensions

`package-manager-cli.bin` has the same dependency check (line ~158). Back it up and neutralise it:

```bash
cd ~/tizen-studio/package-manager
cp package-manager-cli.bin package-manager-cli.bin.orig
sed -i '158s/.*/if false ; then/' package-manager-cli.bin
./package-manager-cli.bin show-pkgs --extension | grep -iE "tv|cert"
./package-manager-cli.bin install --accept-license TV-SAMSUNG-Public TV-SAMSUNG-Extension-Tools \
  TV-SAMSUNG-Extension-Resources TV-SAMSUNG-Public-WebAppDevelopment cert-add-on Certificate-Manager
```

This takes several minutes. It installs `tools/ide/bin/tizen`, `tools/sdb` and a standalone **Certificate Manager** (`tools/certificate-manager/certificate-manager`, an Eclipse RCP app, so no full IDE needed).

## 4. Connect sdb and back up

```bash
export PATH=$HOME/tizen-studio/tools:$HOME/tizen-studio/tools/ide/bin:$PATH
sdb connect 192.168.50.31:26101
sdb devices        # 192.168.50.31:26101  device  UA43T6500AKXXD
sdb shell id       # prints nothing on this firmware (expected per repo README)

git clone https://github.com/DavidNgugi/samsung-tv-unlock.git ~/cleanmysamsungtv-src/repo
cd ~/cleanmysamsungtv-src/repo
TV_IP=192.168.50.31 PROFILE=none tools/backup-tv.sh    # -> ~/Backups/cleanmysamsungtv/<stamp>/
```

I read `tools/setup.sh`, `deploy-launcher.sh` and `backup-tv.sh` before running them; they only build/install a .wgt and (separately) touch Home keys.

## 5. Samsung certificate (needs the user's Samsung account)

The retail TV only accepts apps signed with an author + **distributor certificate bound to the TV's DUID**, issued by Samsung's server after an account login. Nobody can do this on the user's behalf.

Launching the GUI from a non-GUI shell needs the display variables of the desktop session (COSMIC/Wayland with Xwayland on `:1`; read them from a running GUI process: `tr '\0' '\n' < /proc/$(pgrep -o firefox)/environ`):

```bash
cd ~/tizen-studio/tools/certificate-manager
DISPLAY=:1 WAYLAND_DISPLAY=wayland-1 XDG_RUNTIME_DIR=/run/user/1000 BROWSER=firefox GDK_BACKEND=x11 \
  LD_LIBRARY_PATH=$HOME/tizen-dl/shim nohup ./certificate-manager > ~/tizen-dl/cm.log 2>&1 &
```

Without `DISPLAY` it dies with `Eclipse: Cannot open display:`. The user then created a Samsung/TV profile (author cert + distributor cert) and signed in via Firefox (default browser here is Brave, so `BROWSER=firefox` / opening `account.samsung.com` in Firefox was done explicitly). Result: profile `samu`, files in `~/SamsungCertificate/samu/`, registered in `~/tizen-studio-data/profile/profiles.xml`. Verify with `tizen security-profiles list`. The DUID in the profile (`TestDevice`) was `KLCFD3MFZVW2C`.

## 6. Build, install, launch

```bash
cd ~/cleanmysamsungtv-src/repo
export LD_LIBRARY_PATH=$HOME/tizen-dl/shim
tools/setup.sh --tv 192.168.50.31 --profile samu --no-spotify
```

Output ended with `Installed the package: Id(tvunlock02.Launcher)` and `successfully launched pid = 730`. Clean Home (`tvunlock02.Launcher`) is now in the TV's app list.

## Undo

```bash
tizen uninstall -p tvunlock02.Launcher
```

Samsung's Home is untouched by this part; `tools/revert.sh` is only needed if Part 2 (Home key / boot rewrite) is ever applied, which is not available/safe on this TV.

## Dead ends / notes

- Running the stock `.bin` as-is: fails the dependency check, installs nothing (exit code 0, easy to miss).
- `sdb shell` hangs/returns nothing: the repo's backup script wraps it in a 3 s timeout for this reason. No shell => no root and no way to snapshot Home vconf keys.
- Certificate password: stored by Certificate Manager inside `profiles.xml`; `tools/setup.sh` doesn't need it re-entered. Do not commit `~/SamsungCertificate`.

## References

- [DavidNgugi/samsung-tv-unlock](https://github.com/DavidNgugi/samsung-tv-unlock) — the Clean Home guide followed
- [Samsung: Command Line Interface (Tizen TV)](https://developer.samsung.com/smarttv/develop/getting-started/using-sdk/command-line-interface.html) — Web CLI / `tizen` usage, permit-to-install
- [Samsung: Installing TV SDK](https://developer.samsung.com/smarttv/develop/getting-started/setting-up-sdk.html) — TV Extensions + Samsung Certificate Extension
- [brightcraft/moonlight-tizen Installation Guide](https://github.com/brightcraft/moonlight-tizen/wiki/Installation-Guide) — Linux installer URL (`web-ide_Tizen_Studio_6.1_ubuntu-64.bin`, I used the matching `web-cli_` file)
