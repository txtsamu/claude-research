---
type: how-to
tags: [tanchjim, fission, ktmicro, dsp, peq, hidraw, squig-link, iem, eq, crinear-nightfall, cross-rig, fedora]
created: 2026-10-27
last_verified: 2026-10-27
status: current   # applied and saved to flash via SAVE 0x53 (ACK 0x03), bands intact after the self-reboot
---

# Tanchjim FISSION-Rational HiFi dongle: PEQ-match CrinEar Nightfall (target on a different squig.link rig)

Sibling of [tanchjim-fission-ktmicro-dsp-peq-match-tin-hifi-c7.md](tanchjim-fission-ktmicro-dsp-peq-match-tin-hifi-c7.md) (device protocol, SAVE, gotchas live there). Files: `~/sessions/2026-10-26-iem-dsp-eq/` (`fit_nightfall.py`, `nightfall_fission.py`, `data/nightfall/`).

Request: "tune my DSP EQ to sound like CrinEar Nightfall" with `https://squig.link/lab/fernandagunsan/?share=CrinEar_Nightfall`; IEM+dongle = Tanchjim Fission Rational HiFi (31b2:0101).

## Problem: target and baseline are on different rigs
- Nightfall exists only on fernandagunsan's site (REW 5.31, 1/24 oct smoothing, Oct 2026). The Fission is only on CSI-Zone (`Tanchjim Fission AtSDdf`, L only). CSI-Zone has no Nightfall; fernandagunsan has no Fission.
- Fix: estimate a rig offset from Tanchjim IEMs measured on **both** sites (Bunny, Nora, Ola 2, Zero Ultima), median of `fg − csi` (L+R avg, each normalised at 1 kHz, resampled to a log grid, smoothed 1/3 oct), and subtract it from Nightfall. Offset is small below 5 kHz (−0.5…−0.9 dB) but unreliable above 8 kHz (IEM-to-IEM std 2.7 dB at 9 kHz, median +3.4 dB at 10 kHz).

## Steps
```bash
cd ~/sessions/2026-10-26-iem-dsp-eq && mkdir -p data/nightfall && cd data/nightfall
curl -sL -o Nightfall_L.txt "https://squig.link/lab/fernandagunsan/data/CrinEar%20Nightfall%20L.txt"   # and R
curl -sL https://squig.link/lab/fernandagunsan/data/phone_book.json -o phone_book.json   # find file names
curl -sL https://csi-zone.squig.link/data/phone_book.json -o csi_phone_book.json
# shared IEMs, both sites, both channels:
for n in "Tanchjim Bunny" "Tanchjim Nora" "Tanchjim Ola 2" "Tanchjim Zero Ultima"; do ...curl fg_/csi_ L,R...; done
cd ../.. && ./venv/bin/python -I fit_nightfall.py          # fit; --no-rig skips the offset for comparison
```
Fit: Fission EQ-off = CSI AtSDdf minus the old factory bands (36/−0.9/0.39, 604/−0.5/6.75, 6000/+1.7/1.02, 10954/−2.5/0.53, 18860/−2.7/0.46); target = (Nightfall − rig offset) − Fission EQ-off, all normalised at 1 kHz; 5 RBJ peaking bands at 48 kHz, 20 restarts, band windows 40–300 / 150–1500 / 1000–3500 / 3000–6500 / 5000–9500 Hz, gain −8..+3 (top band ≤ 0).

Dead end: first fit over 60–10 kHz let the top band go +3 dB / Q 3 at ~8.9 kHz — it was fitting rig noise above 8 kHz. Fixed by fitting only 60 Hz–8 kHz and forbidding boost in the top band. Without rig correction the fit wanted −5.2 dB at 6.5 kHz and a different shape (needed RMS 1.64 vs 1.12 dB), so the correction matters.

Result (0.12 dB RMS residual over 60–8 kHz, max boost +1.85 dB, no preamp):

| Band | Freq | Gain | Q |
|---|---|---|---|
| 0 | 122 Hz | −1.3 | 1.60 |
| 1 | 291 Hz | +2.0 | 0.72 |
| 2 | 3136 Hz | −1.3 | 0.62 |
| 3 | 3488 Hz | +1.9 | 1.97 |
| 4 | 6048 Hz | −2.1 | 2.68 |

Replaced the C7 bands (60/593/2575/3118/6471). Nothing is fitted above 8 kHz.

## Apply
```bash
sudo ./venv/bin/python -I nightfall_fission.py apply     # RAM, read-back verified (done: all 5 ACK, match True)
sudo ./venv/bin/python -I nightfall_fission.py save      # SAVE 0x53 -> flash (done 2026-10-27, reply 4b00000000530003000000)
sudo ./venv/bin/python -I nightfall_fission.py restore   # factory bands from eq_backup.json -> RAM, then 'save'
```

## Caveats
- Approximation: coupler data, different rigs, one unit standing in for another; no listening A/B or re-measurement yet.
- Nightfall's own sample variation and the Fission's real EQ state when measured are assumptions.

## References
- [CrinEar Nightfall on fernandagunsan's squig.link](https://squig.link/lab/fernandagunsan/?share=CrinEar_Nightfall)
- [CSI-Zone squig.link](https://csi-zone.squig.link/) (Fission baseline, shared Tanchjim IEMs)
