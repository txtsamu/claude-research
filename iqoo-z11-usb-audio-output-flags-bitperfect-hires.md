---
type: investigation
tags: [android, iqoo, redmi, xiaomi, mediatek, vivo, originos, otg, usb-c, audio, usb-dac, hi-res, bit-perfect, audio-policy, poweramp, bitchord, snapdragon-sound, bluetooth-codecs, adb]
created: 2026-10-19
last_verified: 2026-10-19
status: current
---

# iQOO Z11 (I2512): audio output flags, hi-res, bit-perfect and Snapdragon Sound

What this phone's audio stack can actually do for wired USB DACs and Bluetooth, read from the
device over wireless ADB rather than spec sites.

## Device

| | |
|---|---|
| Model | `I2512`, `ro.vivo.product.release.name` = **iQOO Z11 5G** |
| SoC | `ro.soc.model=SM7635` (**Snapdragon 7s Gen 3**), `ro.board.platform=volcano` |
| OS | OriginOS 6, Android 16 (SDK 36) |

Spec sites disagree on the chip. Beebom lists the Z11 with a MediaTek Dimensity 7500. This unit
reports Qualcomm SM7635, so treat the Z11 as having regional/chip variants, and **trust `getprop` over
spec sheets**.

```sh
D=<PHONE_IP>:<wireless-debug-port>
for p in ro.product.model ro.vivo.product.release.name ro.soc.model ro.board.platform ro.build.version.sdk; do
  echo "$p=$(adb -s $D shell getprop $p)"; done
```

## Summary

| Question | Answer |
|---|---|
| Hi-res over USB? | **Yes**, up to whatever the DAC supports (both IEMs tested: 16/24-bit, 44.1-96 kHz) |
| Android 14+ official bit-perfect USB? | **No.** No `AUDIO_OUTPUT_FLAG_BIT_PERFECT` anywhere in the audio policy |
| Mixer-bypass output that reaches USB? | Yes: `direct_pcm` (`AUDIO_OUTPUT_FLAG_DIRECT`, 16/24/32-bit, 8-384 kHz) |
| Guaranteed bit-perfect in practice? | Only via an app's own USB driver (Poweramp `usbx`, UAPP, the BitChord fork). Verified with Poweramp |
| Snapdragon Sound? | **Not installable** (it's a certification, not an app). SM7635 isn't marketed with it |

## 1. Audio policy output flags (the full list)

Active file: `/vendor/etc/audio_policy_configuration.xml`. Variants exist under
`/vendor/etc/audio/sku_volcano*/` and an `.original.xml`. The USB module is the old
`halVersion="2.0"`. **USB headset audio is served by the Qualcomm primary module**
(`{AUDIO_DEVICE_OUT_USB_HEADSET, @:card=1;device=0}`), not by the AOSP `usb` module, which only has
`usb_accessory output`.

```sh
adb -s $D shell cat /vendor/etc/audio_policy_configuration.xml > apc.xml
grep -c BIT_PERFECT apc.xml                                     # 0
grep -n 'sink="USB Headset Out"' -A2 apc.xml
#   sources="primary output,raw,deep_buffer,direct_pcm,voip_rx,mmap_no_irq_out,hifi_playback,haptics output,Telephony Rx"
for f in /vendor/etc/usb_audio_policy_configuration.xml /vendor/etc/audio/sku_volcano/audio_policy_configuration.xml; do
  adb -s $D shell "grep -c BIT_PERFECT $f"; done                # 0 everywhere
```

The mix ports were parsed with a small `python3 -I` script (ElementTree; strip `<xi:include>` first,
then walk `module/mixPort` and match against the `route` whose `sink` is `USB Headset Out`):

### Output (playback)

| Flags | mixPort | Routes to USB headset | Formats / rates |
|---|---|---|---|
| `FAST` + `PRIMARY` | primary output | yes | PCM 16, 48 kHz |
| `FAST` + `RAW` | raw | yes | PCM 16, 48 kHz (low latency) |
| `DEEP_BUFFER` | deep_buffer | yes | PCM 16/24/32/8_24, 48 kHz |
| **`DIRECT`** | **direct_pcm** | yes | **PCM 16/24/32/8_24, 8 kHz-384 kHz** |
| `DIRECT` + `MMAP_NOIRQ` | mmap_no_irq_out | yes | PCM 16/24/32/8_24, 48 kHz (AAudio exclusive/MMAP) |
| *(none)* | **hifi_playback** | yes | *dynamic*: follows the DAC (16/24-bit, 44.1-96 kHz on the IEMs tested) |
| `SPATIALIZER` | spatial output | no | PCM 16, 48 kHz |
| `VOIP_RX` | voip_rx | yes | PCM 16, 8-48 kHz |
| `INCALL_MUSIC` | incall_music_uplink | no | PCM 16, 8-48 kHz |
| *(none)* | haptics output | yes | PCM 16, 48 kHz |
| *(none)* | voice_tx | no | PCM 16, 8-48 kHz |
| *(none)* | usb_accessory output (`usb` module) | no | PCM 16, 44.1 kHz |

### Input (recording)

| Flags | mixPort | Formats / rates |
|---|---|---|
| `MMAP_NOIRQ` | mmap_no_irq_in | PCM 16/24/8_24, 48 kHz |
| `VOIP_TX` | voip_tx | PCM 16, 8-48 kHz |
| *(none)* | primary input, voice_rx | PCM 16, 8-48 kHz |
| *(none)* | record_24 | PCM 24/8_24/float, 8-192 kHz |
| *(none)* | usb_surround_sound | PCM 16/32/float, 8-192 kHz |
| *(none)* | hifi_input | dynamic |

Distinct flags present: `OUTPUT_FLAG_{PRIMARY, FAST, RAW, DEEP_BUFFER, DIRECT, MMAP_NOIRQ,
SPATIALIZER, VOIP_RX, INCALL_MUSIC}` and `INPUT_FLAG_{MMAP_NOIRQ, VOIP_TX}`. **No `BIT_PERFECT`,
no `COMPRESS_OFFLOAD`** in this file.

Runtime confirmation: `dumpsys media.audio_policy` has an empty `Preferred mixer audio
configuration:` section, so no app has (or can have) a bit-perfect mixer attribute set.

### What `DIRECT` means here (and why it isn't bit-perfect)

- A DIRECT output gets its own AudioFlinger direct thread: **one stream at a time, no mixing, no
  resampling, no format conversion**. The app's PCM goes to the HAL in its own rate and format, as
  long as a direct profile matches. `direct_pcm` accepts 16/24/32-bit at up to 384 kHz, so a
  24/96 stream could pass untouched.
- It is **not** the Android 14 bit-perfect guarantee:
  1. Volume can still be applied (by the HAL or in software), so below 100% the samples change.
     `BIT_PERFECT` guarantees no volume processing.
  2. Java apps have no simple public "give me DIRECT" switch for PCM. The policy only picks it when
     format/rate/flags match a direct profile. **Float PCM never matches** (`direct_pcm` has no
     `PCM_FLOAT`), which is why BitChord 1.8's float AudioTrack landed on the mixer (section 3).
  3. The Qualcomm HAL can still convert before the USB card, and that isn't visible without root.
- `hifi_playback` (dynamic profile) is how an app gets the **native rate** (no resample to 48 kHz),
  but it still goes through the mixer.

## 2. USB DAC capabilities (both IEMs)

```sh
adb -s $D shell dumpsys media.audio_policy | grep -A12 '"USB Headset Out"' | grep -E 'Port ID|FORMAT|sampling'
adb -s $D shell dumpsys usb | sed -n '/host_manager/,/_manager/p' | grep -E 'manufacturer|product_name|vendor_id|product_id'
```

| IEM | USB ID | Profiles reported |
|---|---|---|
| Moondrop USB-C DAC cable (Conexant) | | PCM 16 / 24-packed, 44.1/48/88.2/96 kHz, stereo |
| **Moondrop Chu II DSP** (`KTMicro`, `Chu2 DSP`, fw 0.03) | `0x31b2:0x0113` (12722:275) | PCM 16 / 24-packed, 44.1/48/88.2/96 kHz, stereo |

24-bit/96 kHz meets the Japan Audio Society Hi-Res Audio threshold, so wired hi-res works with
either IEM. The 96 kHz ceiling is the DACs', not the phone's (`direct_pcm` allows 384 kHz).

The Android mixer's USB thread by default (`dumpsys media.audio_flinger`, the thread with
`Output devices: 0x4000000`) ran at **48 kHz PCM_32** with nothing special playing. With BitChord
1.8 playing a 44.1 kHz track it switched to **44.1 kHz** (native rate via `hifi_playback`), still
a MIXER thread.

```sh
adb -s $D shell dumpsys media.audio_flinger | awk '/^Output thread/{b=$0;next}{b=b"\n"$0}
  /Output devices: 0x4000000/{print b}' | grep -E 'Output thread|Sample rate|HAL format|Standby'
```

## 3. What players actually do (verified 2026-10-19)

### BitChord 1.8 (`com.music.bitchord`, upstream release): mixer

Even with its "exclusive" option switched on, logcat showed a normal track and none of the fork's
log tags (`UsbDirectDriver`, `UsbIsoStream`, `UsbBitPerfect`):

```
AudioTrack set(): sampleRate 44100, format 0x5 (float), flags 0   -> MIXER thread @ 44.1 kHz
```

Android still listed `usb_headset` as an audio device, and there was no USB-permission popup. The
real exclusive driver is only in the fork (`txtsamu/BitChord`, branch `usb-exclusive-mode`,
package `com.dev.bitchord.benchmark`). See `bitchord-android-usb-exclusive-mode-uac-driver.md`.

### Poweramp (`com.maxmpz.audioplayer`): true exclusive USB (`usbx`)

```sh
P=$(adb -s $D shell pidof com.maxmpz.audioplayer)
adb -s $D logcat -d -v time --pid=$P | grep -E 'usbx|USB lock|usb_audio_stream|dsp_thread'
adb -s $D shell dumpsys media_session | grep -A16 maxmpz | grep -oE 'volumeType=[A-Z]+|max=[0-9]+'
```

```
PSRouterUsbExclusiveLock: USB lock ENGAGED name=Chu2 DSP path=/dev/bus/usb/001/002 output=.../output.usbx
usbxoutput.c: prepare selected alt=2 ch=2 sr=96000 pipeline sr=96000 fmt=s24 srs=0x80 count=1 srs= 96000
usb_audio_stream.c: UAC1 ... vid=0x31b2 pid=0x0113 iface=2 alt=2 ep=0x04 sr=96000 fmt=s24 ch=2 bits=24 ... full-speed packet_rate=1000
media_session: volumeType=REMOTE controlType=ABSOLUTE max=100
```

- No Android output thread was routed to the USB headset while it played. The mixer was fully
  out of the path.
- Volume became remote/absolute (Poweramp/DAC-side volume, not Android's).
- **Caveat:** output was pinned to **96 kHz** (`srs=0x80 count=1`), so 44.1/48 kHz tracks are
  upsampled by Poweramp's resampler (`plugin.resampler3`). That's bit-perfect only for 24/96 sources.
  Fix: Poweramp Settings → Audio → Output → USB DAC (usbx) → sample rate → follow the source.
  Not yet re-verified after the change.

## 4. Bluetooth codecs and Snapdragon Sound

```sh
adb -s $D shell 'ls /system/lib64 /system_ext/lib64 /vendor/lib64' | grep -iE 'aptx|ldac|lhdc|lc3|opus'
#   lib_bt_aptx.so, libopus_n1.so, libvopus_v5_n1.so
adb -s $D shell dumpsys media.audio_policy | grep -oE 'AUDIO_FORMAT_(APTX|LDAC|LHDC|LC3|AAC|SBC|OPUS)[A-Z0-9_]*' | sort -u
#   AAC*, APTX, APTX_ADAPTIVE, APTX_ADAPTIVE_QLEA, APTX_HD, APTX_TWSP, LC3, LDAC, OPUS, SBC
```

- The format list is what the policy knows about, which may be wider than what the BT controller
  negotiates. Ground truth is **Developer options → Bluetooth audio codec** with a headset
  connected (codecs both sides support are selectable).
- **Snapdragon Sound** is a Qualcomm certification bundle (chip + Bluetooth stack + licensing on
  both phone and headset). There is **no APK** that adds it, and anything claiming to is fake.
  Qualcomm's 7s Gen 3 page and product brief mention only Aqstic Hi-Fi DAC / Speaker Max, while the
  non-"s" 7 Gen 3 is the one marketed with the Snapdragon Sound suite. vivo doesn't advertise it
  for the Z11.
- LDAC (990 kbps) is the "Hi-Res Audio Wireless" option if the headset supports it. It's still lossy.

## 5. OTG / USB-C flags on this phone (read 2026-10-19)

Everything OTG-related that `shell` can see. See `iqoo-vivo-otg-keepalive-not-possible-without-root.md`
for the 5-min timer mechanism and why none of this is writable.

```sh
adb -s $D shell getprop | grep -iE 'otg|typec|sys\.usb|persist\.vivo\.phone'
for ns in global system secure; do adb -s $D shell settings list $ns | grep -iE 'otg|usb'; done
adb -s $D shell pm list features | grep -i usb
adb -s $D shell dumpsys usb | sed -n '/port_manager/,/alsa_manager/p'
adb -s $D shell ls -la /sys/devices/virtual/vusb/usb0/
adb -s $D shell grep -n -iE 'otg|vusb|host_mode' /system/etc/init/hw/init.rc /system/etc/init/hw/init.usb.rc /vendor/etc/init/hw/*.rc
```

### System properties

| Property | Value | Meaning |
|---|---|---|
| `persist.vivo.phone.usb_otg` | `Have_otg_usbc` | OTG capability class. `VOtgUtils.isCcOpen()` is false, so the `vivo_otg_status` setting is never used on this model |
| `persist.vivo.phone.otg_param` | `5` | Bitmask. Bit 0 enables the "OTG help" page (signal-compatibility modes via `UsbManager.setEysParameter`), unrelated to the timeout |
| `persist.vivo.otg_silicon_batt_low_thr` | `10` | Battery % below which OTG power is refused (silicon-carbon battery threshold) |
| `sys.usb.controller` | `a600000.dwc3` | Qualcomm DWC3 USB controller |
| `sys.usb.config` / `sys.usb.state` | `mtp,adb` | Gadget-side (device-role) config. Not OTG |
| `sys.usb.vidVendor` / `sys.usb.vidProduct` | `0x2d95` / `0x6001` | vivo USB IDs in device mode |
| `sys.usb.sleep.mode`, `sys.usb.quirk.dev`, `sys.usb.vcar.mode` | `0` | vivo gadget/car-mode switches |
| `sys.usb.typec.*` | **unset** | AOSP init triggers exist (see below) but nothing sets them |

### Settings keys

No `otg*` key exists in any namespace (re-confirmed, matches the 2026-10-11 finding). USB-related
rows only: `global usb_devices_add=1`, `global usb_mass_storage_enabled=1`,
`system show_usb_option=1`, `system usb_first_plug_in=1`, `system volume_music_usb_headset=8`,
`system volume_voice_usb_headset=7`, `secure usb_audio_automatic_routing_disabled=0`,
`secure usb_handle_is_in_game_scene=0`, `secure usb_migration_*`.

### Platform features

`android.hardware.usb.host` and `android.hardware.usb.accessory`.

### USB-C port (`dumpsys usb` → `port_manager`, USB HAL v20)

| Field | Value (Chu II attached) |
|---|---|
| `supported_modes` | **`dual, audio_acc`** (DRP plus analog audio-accessory mode) |
| `current_mode` / `power_role` / `data_role` | `dfp` / `source` / `host` |
| `role_combinations` | source+host, sink+device |
| `can_change_mode` | **true** |
| `can_change_power_role` / `can_change_data_role` | false / false |
| `contaminant_presence_status` | not detected |
| `usb_data_status` | enabled |
| `supports_compliance_warnings` | false |

`can_change_mode=true` means the HAL reports that the port mode (DRP/UFP/DFP) can be changed
through `UsbPort.setRoles`/`UsbManager`, which needs the system-only `MANAGE_USB` permission.
`dumpsys usb` also has test commands (`set-port-roles`, `add-port`, `reset`). **Untested here.**
They're a possible lead for forcing DFP without the vivo switch, but they'd change the live port
while the DAC plays, so they weren't run.

### vivo `vusb` sysfs nodes (`/sys/devices/virtual/vusb/usb0/`)

`host_mode`, **`otg_drp`**, `otg_mode`, **`otg_vbus`**, `sleep_mode`, `usb_log`, `usb_type`,
`usbid_value`, `uevent`. All of them show as `-?????????` to `shell` (SELinux `sysfs_otg`, can't
even stat them). `otg_drp` and `otg_vbus` are newer than the 2020-21 X60 Pro `dwc3-vusb.c`, which
only had `host_mode`/`otg_mode`. That's consistent with the OriginOS 6 driver having changed.

Init scripts loosen the DAC permissions, but SELinux still blocks them:

```
/system/etc/init/hw/init.rc:1562   # add by usb for otg begin
                                    chown system system /sys/devices/virtual/vusb/usb0/otg_mode
                                    chmod 0664 /sys/devices/virtual/vusb/usb0/otg_mode
                                    chmod 0666 /sys/devices/virtual/vusb/usb0/host_mode   <- world-writable mode bits, SELinux still denies shell/apps
/vendor/etc/init/hw/init.vivo.usb.rc: chmod 0666 .../vusb/usb0/usb_log
                                      chmod 0666 .../soc:qcom,pmic_glink:qcom,ucsi/set_ccom
/system/etc/init/hw/init.usb.rc:23  service vusbd /system/bin/vusbd --root_seclabel=u:r:su:s0
```

- AOSP's `on property:sys.usb.typec.mode=dfp|ufp` (and `data_role` / `power_role`) triggers write
  to `/sys/class/dual_role_usb/otg_default/*`, but **`/sys/class/dual_role_usb/` doesn't exist**
  on this kernel, so those triggers are dead. `sys.usb.*` props can't be set from `shell` anyway.
- `/sys/class/typec/` (the modern Type-C class) is permission-denied to `shell`.
- `vusbd` is a vivo USB daemon running with a root seclabel (`/data/vusbd/`, gadget config
  `charging,vusbd`). It's a vivo service/diagnostics channel, not an OTG switch.

## 6. Comparison: Redmi Note 12 Pro 5G (HyperOS 2, MT6877) flags, scanned 2026-10-19

Same scan on the Redmi (`192.168.50.3`, Android 14 / SDK 34, `Config source:
/vendor/etc/audio_policy_configuration.xml`). The main file `xi:include`s
`bluetooth_audio_policy_configuration.xml`, `a2dp_in_…`, `usb_audio_accessory_only_policy_configuration.xml`
and `r_submix_…`. So the AOSP `usb` HAL module (loaded, handle 26) only does USB *accessory*.
**USB headset/device audio is served by MediaTek's primary module**, the same pattern as the iQOO's Qualcomm primary.

```sh
D=192.168.50.3:<port>
adb -s $D shell dumpsys media.audio_policy | grep 'Config source'
for f in audio_policy_configuration.xml usb_audio_policy_configuration.xml bluetooth_audio_policy_configuration.xml \
         a2dp_in_audio_policy_configuration.xml r_submix_audio_policy_configuration.xml; do
  adb -s $D shell cat /vendor/etc/$f > $f; done
grep -c BIT_PERFECT *.xml        # 0 in every file
# parse: inline the xi:includes, then walk module/mixPort and the routes whose sink contains "USB" (python3 -I + ElementTree)
```

| Flags | mixPort | → USB headset | Formats / rates |
|---|---|---|---|
| `PRIMARY` | primary output | yes | PCM 16/32, 44.1-48 kHz |
| `DEEP_BUFFER` | deep_buffer | yes | PCM 16/32, 44.1-48 kHz |
| `FAST` | fast | yes | PCM 16/32, 44.1-48 kHz |
| `VOIP_RX` | voip_rx | yes | PCM 16/32, 16-48 kHz |
| `DIRECT` + `MMAP_NOIRQ` | mmap_no_irq_out | **no** | PCM 16, 48 kHz |
| `INCALL_MUSIC` | incall_music_uplink | no | PCM 16/32, 44.1-48 kHz |
| *(none)* | **hifi_playback** | yes | dynamic (follows the DAC) |
| *(none)* | a2dp output (bluetooth) | | dynamic |
| *(none)* | hearing aid output, r_submix output | | PCM 16 |
| Inputs | primary input, voice tx, FM Tuner input; `MMAP_NOIRQ` mmap_no_irq_in; `VOIP_TX` voip_tx; `FAST` fast input; hifi_input (dynamic); a2dp input; r_submix input | | PCM 16, 8-48 kHz (hifi dynamic) |

Differences from the iQOO:

- **No plain `DIRECT` output at all.** The iQOO has `direct_pcm` (16/24/32-bit, up to 384 kHz)
  routed to USB. The Redmi's only DIRECT port is the 48 kHz MMAP one, and it **doesn't route to USB**.
  So on the Redmi, the only Android-side hi-res path to a USB DAC is the mixer at the DAC's native
  rate via `hifi_playback`.
- No `BIT_PERFECT` either (`Preferred mixer audio configuration:` empty), the same as the iQOO and
  as recorded in `bitchord-android-usb-exclusive-mode-uac-driver.md`. Note: that doc's
  `usb_audio_policy_configuration.xml` (HIDL 2.0, `usb_device output` FAST only) isn't the file
  actually included at runtime. The active config uses the accessory-only variant plus MTK primary.
  Same conclusion.
- Fixed ports top out at 48 kHz, PCM 16/32 (no 24-packed).
- Bluetooth codec libs visible to shell: only `libaivsopus.so` (no `lib_bt_aptx.so`, unlike the iQOO).
- USB-C port: `supported_modes=dual, audio_acc, debug_acc`.

Chu II DSP on the Redmi (`0x31b2:0x0113`): policy profiles **PCM 8 / 16 / 8_24-bit at 44.1/48/88.2/96 kHz**,
plus a fixed 16-bit 44.1/48 profile. With Poweramp playing, the mixer's USB thread sat in standby
(last config 96 kHz PCM_32), and Poweramp's own driver had the DAC:

```
usbxoutput.c: prepare selected alt=2 ch=2 sr=44100 pipeline sr=44100 fmt=s24 srs=0xf0 count=4 srs= 44100 48000 88200 96000
usb_audio_stream.c: UAC1 ... vid=0x31b2 pid=0x0113 iface=2 alt=2 ep=0x04 sr=44100 fmt=s24 ch=2 bits=24 sync=1
media_session (poweramp): volumeType=REMOTE
```

There Poweramp **followed the track's 44.1 kHz** with all four rates allowed (`srs=0xf0 count=4`),
which is bit-perfect for 44.1 kHz sources. On the iQOO the same app was pinned to 96 kHz
(`srs=0x80 count=1`), so that's a per-install Poweramp setting, not a DAC limit.

## Gotchas

- `/proc/asound/cards` and `/proc/asound/card*/stream*` are **permission denied** for `shell`.
  Read DAC formats from `dumpsys media.audio_policy` (device port profiles) or `dumpsys usb` instead.
- The phone's wireless-debugging port changes on every toggle and reboot (seen: 43831 → 44091 → 45021).
- Plugging a USB DAC in **after boot** goes through the vivo OTG path, which normally means the
  5-min cutoff. See `iqoo-vivo-otg-keepalive-not-possible-without-root.md`. With the Chu II
  plugged in at 09:17:16 there was **no detach by 09:23:12** (past the ~5 min mark). Whether the
  OTG switch was used for that attach wasn't confirmed.

## References

- [AOSP: Preferred mixer attributes on USB devices (BIT_PERFECT)](https://source.android.com/docs/core/audio/preferred-mixer-attr)
- [Android Developers: Improve audio playback (setPreferredMixerAttributes)](https://developer.android.com/media/platform/improve-audio-playback)
- [Qualcomm: Snapdragon 7s Gen 3 Mobile Platform](https://www.qualcomm.com/smartphones/products/7-series/snapdragon-7s-gen-3-mobile-platform)
- [Snapdragon 7s Gen 3 product brief (PDF mirror)](https://the-decoder.de/wp-content/uploads/2024/08/Snapdragon-7s-Gen-3-Product-Brief.pdf)
- [Qualcomm: Snapdragon 7 Gen 3 Mobile Platform (Snapdragon Sound suite)](https://www.qualcomm.com/smartphones/products/7-series/snapdragon-7-gen-3-mobile-platform)
- [Qualcomm: Navigating Snapdragon Sound for your devices](https://www.qualcomm.com/snapdragon/news/navigating-snapdragon-sound-for-your-devices)
- [Android Central: What is Snapdragon Sound?](https://www.androidcentral.com/qualcomm-snapdragon-sound)
- [TechRadar: What is Snapdragon Sound?](https://www.techradar.com/audio/audio-streaming/what-is-snapdragon-sound)
- [aptx.com: Snapdragon Sound / aptX phones](https://www.aptx.com/phones)
- [Notebookcheck: Snapdragon 7s Gen 3 specs](https://www.notebookcheck.net/Qualcomm-Snapdragon-7s-Gen-3-Processor-Benchmarks-and-Specs.961224.0.html)
- [Beebom: iQOO Z11 vs iQOO 11 (lists Z11 as Dimensity 7500, contradicts this unit)](https://gadgets.beebom.com/compare/iqoo-z11-vs-iqoo-11-5g)
