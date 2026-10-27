---
type: how-to
tags: [diskos, snowsky-disc, installer, firmware, image, squashfs, bin]
created: 2026-10-27
last_verified: 2026-10-27
status: current
---

# diskOS: where `diskos_*.bin` comes from (you cannot download it; build it)

Request: "add instruction on how to download diskos_*.bin". There is no download. The repo says so in three places (`README.md` "Do not redistribute generated `diskos_*.bin` images. They contain FiiO's root filesystem", `CONTRIBUTING.md:25`, and `build/stage-release.sh:71` which lists `diskos_dev*.bin` / `diskos_public*.bin` as forbidden release files). The image is produced locally from the official FiiO firmware ZIP. The instructions were added to the repo as a new section in `docs/INSTALL.md` (fork `dev`, commit `12f8944`).

## How it was worked out

```bash
cd ~/diskos/diskos
grep -rnIE 'diskos_[A-Za-z0-9_*.-]*\.bin' --include=*.md --include=*.py --include=*.sh .   # README, CONTRIBUTING, stage-release.sh
sed -n 190,240p diskos_installer/service.py     # out_bin = os.path.join(work, f"diskos_{variant}.bin"); work = state.build_dir()
grep -n 'def preflight' -A14 diskos_installer/flasher.py   # IMG_SIZE = 100663296 (96 MiB) and squashfs magic checked
ls -la ~/.local/share/diskos-installer/build/    # diskos_public.bin 96.0M, out.squashfs, stock_rootfs.squashfs(.padded), fw_unzip/
file ~/.local/share/diskos-installer/build/diskos_public.bin   # Squashfs filesystem, little endian, version 4.0, lzo
```

## The recipe

1. Get the official firmware ZIP from FiiO / Snowsky (`SNOWSKY_DISC_update_<date>_v<version>.zip`; supported V2.09, V2.28, V2.40, V2.57). No verified download URL was found, so none is given in the repo doc.
2. Build, answering `n` at the confirmation (never `-y`, which flashes):

   ```bash
   ./diskos-installer install --firmware ~/Downloads/SNOWSKY_DISC_update_*.zip --variant public
   # --variant dev for the dev image; --ui ./mq_ui for your own UI build; --no-ota / --ota-key PATH
   ```

   Order inside `service.py`: extract and validate the stock rootfs, `build_image(... out_bin ...)`, then `flasher.preflight(out_bin)` (needs a Disc in mask-ROM; without one it stops with E110), then the confirm. The image already exists by then.
3. Find `diskos_<variant>.bin` in the installer state dir's `build/` folder: Linux `~/.local/share/diskos-installer/build/` (or `$XDG_DATA_HOME`), macOS `~/Library/Application Support/diskos-installer/build/`, Windows `%LOCALAPPDATA%\diskos-installer\build\`; `DISKOS_INSTALLER_HOME` replaces the part before `build` (`state.py` `_state_base`).

Not re-run in this session: the `install` command itself (the image on disk was built in an earlier session, 2026-10-22, for the `stock-plus-disco` flash; see [[diskos-stock-plus-round-screen-features-and-flash]], which has the same build-only command with `echo n |`). The doc link in `INSTALL.md` first pointed at a README anchor that does not exist (`#support-diskos`); the heading is "License and support", fixed before the commit.
