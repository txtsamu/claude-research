# kt0211l-flasher

Linux flasher for KTMicro Helios-class USB DSP dongles (KT02H20 and KT0211L, e.g. the Tanchjim FISSION-Rational HiFi Edition). Fork of `ktflash.py` (the KT02H20 flasher in `~/archive/.../tooling/kt02h20-flasher`) that adds:

- the `KT_lnv1b_flash_1` image format (vendor KT0211L packages);
- the vendor's **flag=1 flow** (derived from reverse engineering `kt_usb_cmd_tool` 1.3.16): VER then KEY before CHP, write base `0x8000`, INF size+CRC check before the final reset;
- a read-only `identify` command.

Write-up with the full story, commands and RE notes: [../fission-rational-hifi-firmware-upgrade-linux-flasher-ktmicro-kt0211l.md](../fission-rational-hifi-firmware-upgrade-linux-flasher-ktmicro-kt0211l.md)

```bash
python3 -m venv venv && ./venv/bin/pip install pyserial
./venv/bin/python -I -m unittest discover -s . -p "test_ktflash_kt0211l.py"          # offline tests (mock bootloader)
./venv/bin/python -I ktflash_kt0211l.py image  fw.bin                                   # validate + plan, sends nothing
sudo ./venv/bin/python -I ktflash_kt0211l.py identify fw.bin                            # READ-ONLY chip check (dongle then needs a replug)
sudo ./venv/bin/python -I ktflash_kt0211l.py flash fw.bin --execute --yes --no-backup-ok
```

No backup of the original firmware is possible in software (the bootloader has no read command). A failed write leaves the dongle in bootloader mode (`8888:cdc0`), not bricked: replug and re-run. The bootloader accepts the KTM handshake only once per power-up. Only flash an image made for your exact product (the tool aborts before erasing if the bootloader's chip ID differs from the image's).
