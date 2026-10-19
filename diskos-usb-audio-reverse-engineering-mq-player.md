---
type: investigation
tags: [fiio, snowsky-disc, diskos, usb-audio, usb-host, otg, uac, reverse-engineering, ghidra, rea, mips, mq_player, iem, dsp-dongle]
created: 2026-10-19
last_verified: 2026-10-19
status: current
---

# diskOS "USB Audio" (external USB DAC output) — reverse-engineering FiiO's mq_player and fixing it

Goal: use a Type-C DSP IEM cable (Moondrop **Chu II DSP**, `31b2:0113 KTMicro Chu2 DSP`) plugged into the FiiO Snowsky Disc, the way the stock FiiO UI's **USB AUDIO** working mode allows — but under diskOS 1.2.1 (flashed per [fiio-snowsky-disc-diskos-flash-fedora.md](fiio-snowsky-disc-diskos-flash-fedora.md)).

Outcome: works. Native 44.1 kHz and 96 kHz 24-bit to the dongle, verified on device. Fix is commit `83774f8` on `txtsamu/diskos` `fix/usb-dac-workmode`, built with `-DDISKOS_TEST_OUTPUTS`.

## 1. Status in diskOS 1.2.1

- The option exists in source but is compiled out of public builds: `ui/modes.c` only adds the "USB Audio" row under `#ifdef DISKOS_TEST_OUTPUTS` ("device-unverified: test builds only"); `ui/Makefile:24`: `make clean && make EXTRA_CFLAGS=-DDISKOS_TEST_OUTPUTS` (also shows "SPDIF Output", untested here). `docs/HARDWARE.md`: "External USB DAC route exists in source; control absent from normal builds". No GitHub issue asks for it.
- The stock switch sequence was already in diskOS's comments (from the stock UI at 0x46bd90): `0666 3` (out device USB_HOST), `0642 5` (gadget selector = USB host), `0657 8` (LOCALPLAYER work-mode).

## 2. The dongle (PC side, to know what the Disc must drive)

```bash
lsusb | grep 31b2                       # Bus 001 Device 017: ID 31b2:0113 KTMicro Chu2 DSP
cat /proc/asound/card3/stream0          # full speed : USB Audio (UAC1)
#   Playback: S16_LE / S24_3LE, 2ch, 44100 48000 88200 96000, ASYNC endpoint
amixer -c DSP contents                  # 'PCM Playback Volume' 0-100 (-50..0 dB), HID interface for buttons
```

Plain UAC1 — the stock `snd-usb-audio` handles it; no special driver needed.

## 3. Reproduce the failure

Built the test variant in a separate worktree (so the normal `ui/mq_ui` isn't clobbered) and hot-loaded it:

```bash
cd ~/diskos/diskos && git worktree add --detach ../diskos-testout fix/usb-dac-workmode
cd ../diskos-testout/ui
podman run --rm --userns=keep-id -v "$PWD:/src:Z" diskos-ui-builder \
  sh -c 'make clean >/dev/null; make CROSS=$CROSS EXTRA_CFLAGS=-DDISKOS_TEST_OUTPUTS'
cd ~/diskos/diskos && DISKOS_IP=<ip> DISKOS_PW='<pw>' bash tools/diskos-deploy.sh ../diskos-testout/ui/mq_ui
```

Chu2 plugged into the Disc, tap Working Mode > USB Audio → toast **"Connect a USB DAC first"**. A 1 s poll over SSH showed nothing ever enumerated:

```bash
ssh root@<ip> 'cat /sys/class/usb_role/*/role /sys/class/udc/*/state; cat /proc/asound/cards; \
  for d in /sys/bus/usb/devices/*; do [ -f $d/idVendor ] && echo $(cat $d/idVendor):$(cat $d/idProduct); done'
# role=device, only 1d6b:0002 (root hub), no card
```

The role switch is `/sys/class/usb_role/13500000.otg_new-role-switch`; it stays `device`.

## 4. Static analysis — what actually powers the port

Pulled the stock binaries off the device (diskOS keeps them):

```bash
mkdir -p ~/diskos/re && cd ~/diskos/re
ssh root@<ip> 'cat /usr/bin/mq_player' > mq_player_257     # md5 ff7beab94287f586d6faa2b51924c901 (dynamically linked MIPS32r2)
ssh root@<ip> 'cat /usr/bin/mq_ui'     > mq_ui_stock_257   # md5 8795cf93b17867d8b119c1ee34c72249
strings -n 5 mq_player_257 | awk 'length($0)<140' | grep -i -E 'usb_role|otg|usb_?host|/proc/asound|SGM|USB_HOST'
```

(`awk length<140` matters — one huge binary blob line otherwise drowns the output.) Key strings: `echo host > /sys/class/usb_role/13500000.otg_new-role-switch/role`, `Error SGM41513_OTG_ON ioctl` (SGM41513 = charger IC with OTG boost → 5 V VBUS), `set out device USB_HOST!`, `set out device USB_HOST_NULL!`, `on_usb_audio_add`, `/proc/asound/card1`.

### rea (morluto/rea) — tried, refused this target

```bash
npm install --global --prefix ~/.local rea-agents@6.7.0
export GHIDRA_INSTALL_DIR=$HOME/opt/ghidra_12.1.4_PUBLIC JAVA_HOME=/usr/lib/jvm/java-21-openjdk
rea search ~/diskos/re/mq_player_257 "otg_new-role-switch" --provider ghidra --format json
# capability_unavailable: ghidra "architecture_unsupported":
#   "EF_MIPS_NAN2008 requires separate verification of NaN encoding semantics in this Ghidra lane."
# hopper/ida/kuna: no MIPS lane at all
```

The Disc's toolchain builds everything NaN2008, so rea 6.7.0 can't open any of FiiO's binaries. Used Ghidra headless directly instead.

### Ghidra headless setup

```bash
sudo dnf install -y java-21-openjdk-devel
mkdir -p ~/opt && cd ~/opt
gh release download Ghidra_12.1.4_build -R NationalSecurityAgency/ghidra -p 'ghidra_12.1.4_PUBLIC_20260921.zip'
unzip -q ghidra_12.1.4_PUBLIC_20260921.zip
```

Script 1 — find strings, list xrefs, decompile every referencing function (`$SCRATCH/ghidra-scripts/UsbHostXrefs.java`; needles can be passed as script args):

```java
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.data.StringDataInstance;
import ghidra.program.model.symbol.*;
import java.util.*;

public class UsbHostXrefs extends GhidraScript {
    static final String[] NEEDLES = {
        "role-switch/role", "SGM41513_OTG_ON", "usb_host_otg_control", "set_usb_host",
        "on_usb_host_add", "on_usb_audio_add", "USB_HOST!", "USB_HOST_NULL",
        "/proc/asound/card1", "uac_already", "get usb_audio info failed"
    };
    @Override
    public void run() throws Exception {
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        Set<Function> done = new LinkedHashSet<>();
        Listing listing = currentProgram.getListing();
        String[] needles = getScriptArgs().length > 0 ? getScriptArgs() : NEEDLES;
        for (Data d : listing.getDefinedData(true)) {
            if (!d.hasStringValue()) continue;
            String s = StringDataInstance.getStringDataInstance(d).getStringValue();
            if (s == null) continue;
            for (String n : needles) {
                if (!s.contains(n)) continue;
                println("STRING @" + d.getAddress() + " \"" + s.trim() + "\"");
                for (Reference r : getReferencesTo(d.getAddress())) {
                    Function f = getFunctionContaining(r.getFromAddress());
                    println("  xref " + r.getFromAddress() + " in " + (f == null ? "?" : f.getName() + " @" + f.getEntryPoint()));
                    if (f != null) done.add(f);
                }
            }
        }
        for (Function f : done) {
            DecompileResults res = di.decompileFunction(f, 60, monitor);
            println("\n===== FUNC " + f.getName() + " @" + f.getEntryPoint());
            println(res.decompileCompleted() ? res.getDecompiledFunction().getC() : "decompile failed: " + res.getErrorMessage());
        }
    }
}
```

Script 2 — decompile the function at an address, creating it if Ghidra's auto-analysis missed it (several xrefs came back `in ?`):

```java
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;

public class DecompAt extends GhidraScript {
    @Override
    public void run() throws Exception {
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        for (String a : getScriptArgs()) {
            Address addr = toAddr(a);
            Function f = getFunctionContaining(addr);
            if (f == null) {
                Function prev = getFunctionBefore(addr);
                Address start = prev == null ? addr : prev.getBody().getMaxAddress().next();
                while (getInstructionAt(start) == null && start.compareTo(addr) < 0) start = start.add(4);
                disassemble(start);
                f = createFunction(start, null);
            }
            println("\n===== FUNC " + (f == null ? "none@" + a : f.getName() + " @" + f.getEntryPoint()) + " (for " + a + ")");
            if (f == null) continue;
            DecompileResults r = di.decompileFunction(f, 60, monitor);
            println(r.decompileCompleted() ? r.getDecompiledFunction().getC() : "decompile failed: " + r.getErrorMessage());
        }
    }
}
```

Run (first import does the full auto-analysis, a few minutes; later runs reuse the project with `-process … -noanalysis`):

```bash
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk
G=~/opt/ghidra_12.1.4_PUBLIC/support/analyzeHeadless; S=$SCRATCH
$G $S/ghidra-proj mqplayer -import ~/diskos/re/mq_player_257 -overwrite \
   -scriptPath $S/ghidra-scripts -postScript UsbHostXrefs.java > usbhost_decomp.txt 2>&1
$G $S/ghidra-proj mqplayer -process mq_player_257 -noanalysis \
   -scriptPath $S/ghidra-scripts -postScript DecompAt.java 0x004f3b34 0x004f3bc0 > uevent_decomp.txt 2>&1
```

### Findings (mq_player V2.57)

| Address | Function (source file from log strings) | What it does |
|---|---|---|
| 0x4e5af4 | `loop_mode_handle_thread` (all_mode_control.c), polls every 100 ms | Applies the `0642` gadget selector. **Mode 5**: close UAC/storage gadget if open → `sleep(1)` → `echo host > …/role` → `set_out_device(0,3)` → `FUN_004e332c(1)` = **SGM41513 OTG_ON** (ioctl `0x2000492c` on `/dev/sgm41513`). Mode 0: OTG off, `echo device`, restore I2S3 out. |
| 0x47bf24 | `set_out_device` (pcm_control_interface_out.c) | case 3: `access("/proc/asound/card1")` — present → `USB_HOST` (3); absent → `USB_HOST_NULL` (7, silent sink). Hard-coded **card1**. |
| 0x4f39c4 | `on_usb_audio_add` (uevent_handler.c) | If out_dev is 3 or 7: re-assert OTG, `set_out_device(0,3)` again, read the DAC's rates and cap at 96 kHz or 384 kHz (flag at 0x83a77c), log `[USB_DAC] vid=… pid=…` from `/sys/class/sound/cardN/device/modalias`, init the USB DAC. |
| 0x4e332c / 0x4e3484 | OTG power on/off | `/dev/sgm41513` ioctls; skips boost when an external charger is detected (`FUN_004e6820()==1`). |

So stock is self-healing: `0642 5` → host role + VBUS (output parked on `USB_HOST_NULL` because no card exists yet) → dongle enumerates as card1 → `on_usb_audio_add` moves the output to the real `USB_HOST`.

**Root cause in diskOS:** `out_switch()` and `osw_tick()` refused `OUT_USB` unless `/proc/asound/card1/usbid` already existed — but nothing powers the port until `0642 5` is sent. Chicken-and-egg; the option could never work.

## 5. Fix (`ui/modes.c`, commit 83774f8)

- Removed both `!out_usb_card_ok()` pre-checks.
- After the `0666 3 / 0642 5 / 0657 8` sequence lands, start a 250 ms timer (`usbw_tick`): wait up to `OUT_USB_WAIT_MS` 8000 for `/proc/asound/card1/usbid`; once seen, wait `OUT_USB_SETTLE_MS` 1000 for `on_usb_audio_add`, then toast "USB DAC connected" and resume playback (not before — resuming earlier would play into `USB_HOST_NULL`).
- Timeout → send the full internal sequence back, toast "No USB DAC found - internal DAC restored" (or "USB DAC not on card1 …" if a USB card exists at another index, since the player only looks at card1). Falls into the existing recovery-pending loop if even that fails.
- `modes_output_busy()` includes the wait timer so no other route/source command can interleave.

## 6. Verified on device

Monitor (1 s SSH poll of role/udc/cards/USB IDs + filtered player log) during the tap:

```
STATE role=none   ...                                   (Local, idle)
STATE role=host   cards= 0 [x2000                       (0642 5 handled)
STATE role=host   cards= 0 [x2000 ; 1 [DSP ; usb=31b2:0113   (VBUS on, Chu2 enumerated as card1)
player: on_usb_audio_add / usb_audio hw:1,0 / set out device USB_HOST! / [USB_DAC] vid=31b2 pid=0113
```

User confirmed audio in the IEMs. Format check (`/proc/asound/card1/pcm0p/sub0/hw_params` vs. the FLAC STREAMINFO read through the player's open fd — `head -c 4096 /proc/$(pidof mq_player)/fd/N`, because the album path contained a fullwidth character that broke shell quoting):

| Source FLAC | Player `audio_track_create` | Sent to Chu2 |
|---|---|---|
| 16-bit / 44.1 kHz | 24-bit / 44.1 kHz | `S24_3LE` 44.1 kHz (zero-padded, lossless, no resample) |
| 24-bit / 96 kHz | 24-bit / 96 kHz | `S24_3LE` 96 kHz (native) |

Not verified: whether the Disc's software volume/EQ alters samples — keep Disc volume max / EQ off and use the dongle's volume for strict bit-perfect.

## Open items

- Unplugging the dongle while on USB Audio: player has `on_usb_audio_remove` / USB_HOST_NULL handling; diskOS does not yet auto-return to the internal DAC. Switch Working Mode back to Local Playback manually.
- SPDIF Output row (also enabled by `DISKOS_TEST_OUTPUTS`) is untested.

## References

- [rea (Reverse Engineer Anything) — README](https://github.com/morluto/rea)
- [rea CLI and evidence guide — native commands, provider selection](https://github.com/morluto/rea/blob/main/docs/cli.md)
- [Ghidra 12.1.4 release](https://github.com/NationalSecurityAgency/ghidra/releases/tag/Ghidra_12.1.4_build)
- [diskos docs/HARDWARE.md — USB host audio route "absent from normal builds"](https://github.com/b0hemia/diskos/blob/main/docs/HARDWARE.md)
- [diskos docs/DEV_WORKFLOW.md — hot-reload over SSH, `--ui` reflash](https://github.com/b0hemia/diskos/blob/main/docs/DEV_WORKFLOW.md)
- [txtsamu/diskos fix/usb-dac-workmode](https://github.com/txtsamu/diskos/tree/fix/usb-dac-workmode)
