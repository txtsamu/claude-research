---
type: how-to
tags: [tanchjim, fission, ktmicro, dsp, peq, hidraw, squig-link, iem, eq, crinear-daybreak, fedora]
created: 2026-10-28
last_verified: 2026-10-28
status: current   # applied and saved to flash via SAVE 0x53 (ACK 0x03), bands intact after the self-reboot
---

# Tanchjim FISSION-Rational HiFi dongle: PEQ-match CrinEar Daybreak (same-rig, no offset needed)

Third sibling after [C7](tanchjim-fission-ktmicro-dsp-peq-match-tin-hifi-c7.md) (device protocol, SAVE, gotchas live there) and [Nightfall](tanchjim-fission-peq-match-crinear-nightfall-cross-rig.md). Files: `~/sessions/2026-10-26-iem-dsp-eq/` (`fit_daybreak.py`, `daybreak_fission.py`, `data/daybreak/`).

Request: "I just connected my DSP, set the EQ so it will sound like CrinEar Daybreak" with `https://csi-zone.squig.link/?share=CrinEar_Daybreak`, then "check claude-research on how to do it". Dongle: Fission Rational HiFi (`lsusb` -> 31b2:0101).

## Why this one is easy
Daybreak is on **CSI-Zone**, the same rig as the Fission baseline (`Tanchjim Fission AtSDdf`, L only), so the cross-rig offset step from the Nightfall doc is skipped. Daybreak only has an **R** file (`CrinEar Daybreak L.txt` is a 404, the curl writes an empty file), so the target is R-only against an L-only Fission: a small channel-asymmetry assumption.

## Steps
```bash
cd ~/sessions/2026-10-26-iem-dsp-eq && mkdir -p data/daybreak && cd data/daybreak
curl -sL https://csi-zone.squig.link/data/phone_book.json -o pb.json && grep -n -i daybreak pb.json   # file "CrinEar Daybreak"
curl -sL -o Daybreak_R.txt "https://csi-zone.squig.link/data/CrinEar%20Daybreak%20R.txt"            # L = 404
cd ../.. && ./venv/bin/python -I fit_daybreak.py
```
`fit_daybreak.py` = `fit_nightfall.py` with the rig-offset block replaced by `night = curve([Daybreak_R.txt])`. Same method: Fission EQ-off = CSI AtSDdf minus the old factory bands, target = Daybreak − Fission EQ-off (both normalised at 1 kHz), 5 RBJ peaking bands at 48 kHz, 20 restarts, fit 60 Hz–8 kHz only, band windows 40–300 / 150–1500 / 1000–3500 / 3000–6500 / 5000–9500 Hz, gain −8..+3, top band ≤ 0.

Result (raw difference 1.12 dB RMS, fit residual 0.16 dB RMS, max boost +2.53 dB, no preamp):

| Band | Freq | Gain | Q |
|---|---|---|---|
| 0 | 48 Hz | +2.7 | 0.60 |
| 1 | 307 Hz | +1.4 | 1.08 |
| 2 | 2097 Hz | −1.1 | 3.00 |
| 3 | 4924 Hz | +1.4 | 0.54 |
| 4 | 6618 Hz | −2.6 | 3.00 |

Band 2 and 4 sit at the Q=3 bound, band 0 at the low edge of its window; nothing is fitted above 8 kHz.

## Apply
```bash
sed -e 's/Nightfall/Daybreak/g; s/nightfall/daybreak/g; s/NIGHTFALL/DAYBREAK/g' nightfall_fission.py > daybreak_fission.py   # then edit the DAYBREAK band list
sudo -n ./venv/bin/python -I daybreak_fission.py apply     # RAM, read-back verified: all 5 ACK, match True
sudo -n ./venv/bin/python -I daybreak_fission.py save      # SAVE 0x53 -> flash, reply 4b00000000530003000000
sudo -n ./venv/bin/python -I daybreak_fission.py restore   # factory bands from eq_backup.json -> RAM, then 'save'
```
Observation: before applying, the flash still held the **C7** bands (60/593/2575/3118/6471), not the Nightfall ones, so the Nightfall EQ had not persisted (or had been reverted). `sudo -n` worked in this session (no classifier block).

## Caveats
- Approximation: coupler data, R-vs-L, one unit standing in for another; no listening A/B or re-measurement.
- +2.5 dB peak digital boost with no preamp (preamp reg `0x66` is deliberately never written); loud full-scale tracks could clip slightly.
- Revert: `restore` then `save`.

## References
- [CrinEar Daybreak on CSI-Zone squig.link](https://csi-zone.squig.link/?share=CrinEar_Daybreak)
- Protocol sources as in the [C7 doc](tanchjim-fission-ktmicro-dsp-peq-match-tin-hifi-c7.md#references)
