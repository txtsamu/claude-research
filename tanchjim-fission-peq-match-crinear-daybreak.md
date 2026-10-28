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

## Cross-check on other squig.link rigs (2026-10-28)
Which sites have both IEMs: scanned all 125 sites in `https://squig.link/squigsites.json` (`scan_sites.py`: fetch each `<site>/data/phone_book.json`, flatten every string, regex `daybreak` / `fission`). Nine have both: csi-zone, soundignity (byte-identical mirror of csi-zone's Fission AtSDdf L and Daybreak R, so no new information), atechreviews, audioamigo, timmyv, practiphile, treblewellxtended, pw, jaytiss.

Independent data from atechreviews (`Daybreak`, `Fission DSP (Default)`) and audioamigo (`Daybreak`, `Fission Brass Default DSP`), both L+R (`compare_daybreak_sites.py`; note these files are in *descending* frequency order, sort before `np.interp`). Same method as above, EQ-off baseline = OLD factory bands.

| Site | Needed vs current-band residual | Fresh fit |
|---|---|---|
| csi-zone | 0.16 dB RMS | 48 Hz +2.7, 307 Hz +1.4, 2.1k -1.1, 4.9k +1.4, 6.6k -2.6 |
| atechreviews | 0.56 | 55 Hz +2.5, 282 Hz +1.8, 6.4k -3.3, little 3-5 kHz boost |
| audioamigo | 1.13 | bass needs only about +0.6 dB at 60 Hz, 6.9k -4.2, 8k -1.6 |

- Agreement: a 6.3-6.9 kHz dip (-2.6..-4.2 dB, Q ~3) on all three; bass lift ~+2.5 at 50-60 Hz and ~+1.5 at 300 Hz on csi-zone and atechreviews.
- Disagreement: audioamigo wants almost no bass lift; csi-zone wants +1 dB at 3-5 kHz where atechreviews wants ~0. Spread between sites is 0.4-0.95 dB (std), which is larger than the 0.16 dB single-site fit error, so the 0.16 figure overstates real confidence.
- Baseline sensitivity: for csi-zone, subtracting the NEW (Jun 2025 firmware) factory bands instead of OLD raises the current-band residual from 0.16 to 0.67 dB. Which firmware the measurement dongle ran is unknown.
- **Median consensus (applied + saved 2026-10-28, replaces the csi-zone-only bands):** per-frequency median of the 3 needed curves, then the same fit: 49 Hz +2.6 Q0.63, 309 Hz +1.4 Q1.04, 2901 Hz +0.5 Q3.0, 6500 Hz +2.1 Q1.54, 6485 Hz -4.2 Q3.0 (max boost +2.5 dB). Residual vs csi/atech/audioamigo = 0.33/0.38/1.03 (csi-zone-only bands: 0.16/0.56/1.13; mean consensus: 0.46/0.56/0.76). Median is robust to the one outlier site (audioamigo's bass). Bands 3 and 4 are a broad +2.1 dB and a narrow -4.2 dB at the same ~6.5 kHz, i.e. one asymmetric notch shape; band 3 sits on the 6500 Hz window edge. SAVE ACK 0x03. `daybreak_fission.py apply` = median bands, `apply-csi` = previous csi-zone-only bands, then `save`.
- Consensus fit (mean of the 3 needed curves): 53 Hz +1.9 Q0.8, 302 Hz +1.2 Q0.97, 2888 Hz +0.6 Q3, 5451 Hz +0.9 Q1.95, 6606 Hz -2.9 Q3; max boost +1.9 dB. Residual vs csi/atech/audioamigo = 0.46/0.56/0.76 against 0.16/0.56/1.13 for the applied bands. Not applied; the applied csi-zone bands remain on the dongle.

## Caveats
- Approximation: coupler data, R-vs-L, one unit standing in for another; no listening A/B or re-measurement.
- +2.5 dB peak digital boost with no preamp (preamp reg `0x66` is deliberately never written); loud full-scale tracks could clip slightly.
- Revert: `restore` then `save`.

## References
- [CrinEar Daybreak on CSI-Zone squig.link](https://csi-zone.squig.link/?share=CrinEar_Daybreak)
- Protocol sources as in the [C7 doc](tanchjim-fission-ktmicro-dsp-peq-match-tin-hifi-c7.md#references)
