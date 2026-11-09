Scripts behind `../horizon-offline-launcher-linux-prepare-failing.md`.

- `build_minecraft_dir.py`: builds `~/.minecraft` for 26.3 (libraries + assets from Mojang's manifest, your own `client.jar`). Run from a folder holding `26.3.json`. Needs `~/Downloads/client.jar`.
- `launch_vanilla_demo.py`: launches the official 26.3 client in `--demo` mode (no account) with the manifest's default JVM args. Run from a folder holding `26.3.json`, with `natives/` and `vanilla-gamedir/` subfolders.
- `sample.sh PID [N]`: prints CPU% of one core and RSS every 2 s, N times.
