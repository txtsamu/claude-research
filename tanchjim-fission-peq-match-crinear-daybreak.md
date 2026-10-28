---
type: how-to
tags: [tanchjim, fission, ktmicro, dsp, peq, hidraw, squig-link, iem, eq, crinear-daybreak, fedora]
created: 2026-10-28
last_verified: 2026-10-28
status: current   # (see the T-nozzle section for what is applied now) applied and saved to flash via SAVE 0x53 (ACK 0x03), bands intact after the self-reboot
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

## All-site comparison and recommendation (2026-10-28)
Pulled Daybreak + a Fission from the other five sites too (`fetch_more_sites.py`: timmyv, practiphile, treblewellxtended, pw, jaytiss), built one "needed correction" curve per site (`analyze_sites.py`; Daybreak minus Fission, L+R where both exist, normalised at 1 kHz; csi-zone/atechreviews/audioamigo are DSP-jack Default so the OLD factory bands are subtracted, the rest are treated as plain Fission = EQ off), then compared candidate EQs and ran leave-one-site-out (`loo_bands.py`). Rigs are mostly DIY couplers/mics, files differ in sort order and point count (the loader sorts and tolerates commas).

Needed correction (dB) per site at 60 / 200 / 2k / 6k / 6.5k / 8k Hz: csi +2.5/+1.3/-0.3/-0.5/-1.4/+0.3; atech +2.7/+1.6/-0.3/-1.6/-2.1/+0.2; audioamigo +0.6/+0.1/+0.3/-1.5/-3.2/-1.8; timmyv +2.6/-0.8/-1.1/-0.6/-0.2/+0.6; practiphile +1.7/-1.2/-1.5/-2.4/-3.2/-1.6; treblewell -0.5/-2.7/-1.7/-1.7/-2.9/-1.0; pw (L only) -1.1/-2.9/-1.4/-3.6/-4.0/-3.6; jaytiss +2.0/-1.0/-0.5/-2.1/-3.7/-3.3. Median: +1.8/-0.9/-0.8/-1.6/-3.0/-1.3.

Findings:
- Only the **6.5-6.8 kHz dip** is robust: 6 of 8 sites want -2..-4 dB there.
- Bass/low-mid is contested: csi-zone and atechreviews want +1.3..+1.6 dB at 200 Hz, five others want 0..-3. Treblewell nozzle variants alone differ by 0.17-0.74 dB RMS, and the Fission's nozzle/switch setting of the user's unit is not known.
- The csi-zone-only and 3-site-median EQs score *worse* than no EQ averaged over all 8 sites (mean RMS 1.44 / 1.36 vs 1.28 dB; worst 2.9 / 2.8).
- Leave-one-site-out, mean RMS (no EQ 1.28): notch only 1.16, notch + 488 Hz 1.13, 3 bands 1.23, 5 bands 1.24. Extra bands fit their own sites better (in-sample 1.06) but do not generalise.
- Recommendation: one notch ~6.8 kHz -2.9 dB Q 2.8 (others 0 dB), all-site mean 1.14 / worst 1.87 dB, no boost so no clipping risk. Optional +1.1 dB at 488 Hz Q 2.8 gains only 0.02 dB (noise). Add bass lift only if the user's nozzle/switch matches csi-zone's `AtSDdf` and a listening A/B prefers it.
- Median-of-8 5-band fit for reference: 175 Hz -1.3 Q1.86, 480 Hz +1.0 Q1.41, 2113 Hz -1.1 Q1.38, 2702 Hz +1.1 Q3, 6836 Hz -3.1 Q3 (max boost +0.9; mean 1.06 in-sample, 1.21 leave-one-out).

## User's actual setup: Atmosphere switch + T (titanium) nozzle (2026-10-28) - current applied EQ
The csi-zone Fission file used above (`AtSDdf`) is the **S** nozzle on the DSP jack, so everything before this section was fitted to the wrong nozzle. csi-zone's file names encode it (`AtT3` = switch: Atmosphere; filter: T; jack: analog 3.5mm). Four sites have a T-nozzle Atmosphere/Default analog Fission (= EQ-off, so no factory-band guess): csi-zone `Tanchjim Fission AtT3` (L only), atechreviews `(Nozzle T Switch Default)`, audioamigo `Titanium Default`, practiphile `Titanium Atmosphere` (R only). Scripts: `fetch_t_nozzle.py`, `analyze_t.py`.

- Sites agree much better with one nozzle: needed correction at 60 / 2k / 5k / 6.5k / 8k Hz is +3.4 / -2.0 / -1.6 / -2.2 / -1.9 dB (median), between-site std 0.3-0.9 dB (8-site mix was ~1-1.5).
- Leave-one-site-out RMS: 5-band 0.63 dB vs no EQ 1.28 (notch+low 0.86, notch only 1.07). Here extra bands do generalise, unlike the mixed-nozzle set.
- Versus the 4 T sites (mean RMS): no EQ 1.28; previously applied S-based median-of-3 1.29; 8-site notch-only 1.13; T-median 5-band 0.54.
- Factory-EQ side check: csi `AtSDdf` (DSP Default) minus `AtS3` (analog), both S: -1.0 @60, -1.7 @100, -2.6 @230, -1.7 @310, -0.7 @3k dB; the OLD factory bands model it with 1.33 dB RMS error, NEW with 1.65, flat 1.66 (neither fits well; above 8 kHz unreliable).

**Applied and saved (SAVE ACK 0x03, bands intact after reboot):** 66 Hz +3.0 Q2.24, 549 Hz +1.3 Q1.70, 2216 Hz -2.3 Q1.83, 3214 Hz +1.3 Q2.32, 7073 Hz -2.0 Q0.74. Caveats: the 66 Hz gain is at the +3 dB search bound (median need there is +3.4) and is a +3 dB peak with no preamp (clipping risk on loud bass-heavy tracks); coupler data below ~60 Hz is unreliable; csi/practiphile Fission files are single-channel. `daybreak_fission.py apply` = these bands, `apply-m3` = previous median-of-3, `apply-csi` = csi S-only, `restore` = factory.

### Wider search (2026-10-28): non-squig.link sources and a missed database
- `scan_sites.py` computed the wrong URL for the Super* Review database (its `urlType` is root, so it lives at `https://squig.link/data/phone_book.json`, not `/lab/superreview/`); it reported it as a failed 404. It has both IEMs. Fix when scanning: treat the root site as `https://squig.link/`. (Also failed with 404, not retried: `dhrme.squig.link/headphones`, `ideru.squig.link`.) A broader name regex (`fisson|fision|tanchjim...`) found no further Fission entries.
- Outside squig.link: Crinacle's `graph.hangout.audio/iem/711/` and `/5128/` have Daybreak but no Fission; `earphonesarchive.squig.link` (5128) has Daybreak (silicone/foam/Meta foam tips) but no Fission; RTINGS has Daybreak but its graphs are paywalled. Web search found no other Fission FR data. So squig.link is the only source with both.
- Super* Review labels nozzles by colour: silver / nickel / gold. Mapped to S/T/C by comparing each nozzle's change relative to silver with csi-zone's labelled files (`analyze_sr.py`): nickel-minus-silver vs csi T-minus-S: 0.28 dB RMS apart, correlation +0.92; gold matches C (0.25). So **nickel = T** (inferred, not stated by the site).
- Fifth T-nozzle source (Daybreak default L+R minus Fission nickel/Atmosphere L+R, `analyze_t5.py`): needed correction +3.0 @60, -1.9 @2k, -3.5 @5k, -2.5 @6.5k, -3.5 @8k. The EQ applied from the first four sites scores **0.62 dB RMS on this unseen site vs 1.44 with no EQ** (a genuine out-of-sample check). Refit on all five: 66 Hz +3.0 Q2.44, 561 Hz +1.4 Q1.74, 2235 Hz -2.2 Q1.75, 3108 Hz +1.3 Q2.61, 7631 Hz -2.3 Q0.71; mean RMS 0.55, identical to the applied EQ, so nothing was changed.
- Insertion depth matters a lot: on Super* Review, Daybreak shallow vs default insertion differ by 1.66 dB RMS, deep by 0.77. This is a likely source of between-site disagreement.

## Same EQ on the FiiO JA11 (analog) (2026-10-28) - superseded by the Chu II correction below
Request: "I just connected my DAC, check claude-research and apply CrinEar Daybreak EQ, but research again if there is EQ reference for my device". Connected: JA11 (`lsusb` 2972:0102, ALSA card `JA11`, PipeWire sink `alsa_output.usb-FIIO_JadeAudio_JA11...analog-stereo` RUNNING). It held the C7 bands in USER1 (preset 3).

- The JA11 is a flat DAC and the baseline used above (Fission T nozzle, Atmosphere, **analog 3.5 mm**, EQ-off) is exactly the signal path through the JA11, so the T-nozzle bands transfer unchanged (no factory-band subtraction needed, unlike the Tanchjim DSP dongle). Assumption: the IEM on it is the Fission with the T nozzle (the JA11 doc's "which IEM" caveat still applies).
- Re-search: web search for Tanchjim Fission FR measurements found nothing beyond what the all-site scan already covered (squig.link is the only source with both IEMs; no Crinacle/RTINGS Fission data), so the fit was not changed.
- Script: `~/sessions/2026-10-26-iem-dsp-eq/ja11_daybreak.py` = `ja11_c7.py` with the band list replaced (same hidraw protocol, backup, RAM read-back check before save, see [the JA11 doc](fiio-ja11-peq-match-tin-hifi-c7-hidraw.md)):
```bash
sudo -n ./venv/bin/python -I ja11_daybreak.py read      # showed C7 bands, preset 3
sudo -n ./venv/bin/python -I ja11_daybreak.py           # apply + verify + save USER1
sudo -n ./venv/bin/python -I ja11_c7.py restore         # JA11 factory USER1 back (ja11_backup.json)
```
- Applied and read back after the save: 66 Hz +3.0 Q2.24, 549 Hz +1.3 Q1.70, 2216 Hz -2.3 Q1.83, 3214 Hz +1.3 Q2.32, 7073 Hz -2.0 Q0.74, preset 3 active. Not yet re-checked after an unplug/replug. Same +3 dB no-preamp clipping caveat (JA11 global gain `0x17` deliberately untouched).

### Correction: the IEM on the JA11 is the Moondrop Chu II (2026-10-28)
The user then said the earphone on the JA11 is the **Moondrop Chu II** (3.5 mm cable version, not the DSP USB-C one), so the Fission T-nozzle bands above are wrong for the JA11 and were replaced. Because the JA11 is a flat DAC, the baseline is the plain analog Chu II measurement (Pragmatic Audio found the DSP cable at 0 dB DSP gain identical to analog, see [the Chu II doc](moondrop-chu2-dsp-ktmicro-peq-match-tin-hifi-c7.md)).

Sources: re-ran the all-site scan with a Chu regex (`scan_chu2.py` = `scan_sites3.py` with `chu\s*(2|ii|two)\b|chu2`, and the root site `https://squig.link/` URL fixed). 21 databases list both Daybreak and a Chu II; `fetch_chu2.py` downloaded Daybreak + plain "Moondrop Chu 2/II" (L+R where present) from 15 of them (hangout.audio, banzai1122, timmyv, boizoff, sl0the missed on file-name guesses, not retried). Pitfall: build the URL with `%20`, not a literal space (the first run returned nothing). soundignity is a byte mirror of csi-zone, so it was dropped; 14 sites remain (csi-zone, atechreviews, audioamigo, aden, aftersound, bassaudio, foxtoldmeso (5128), gadgetrytech, lown-fi, pw, sai, treblewellxtended, squig.link Super*Review, fernandagunsan). Each site's rig is internally consistent, so per site: needed = Daybreak - Chu II, both normalised at 1 kHz.

`analyze_chu2.py` (per-site table, median, 5-band fit 60 Hz-9.5 kHz, gain -8..+3, Q 0.4-3, leave-one-site-out). Median needed correction: -1.1 @60, -1.8 @100, -1.3 @200, **+1.3 @500**, -1.1 @2k, -1.0 @3k, -1.4 @4k, -1.7 @5k, -1.2 @6k, -1.8 @8k. Between-site std is under 1 dB up to 4 kHz (0.2 dB at 500 Hz) but 1.4-2.3 dB above 5 kHz, so the treble bands are the least certain. Fit: mean RMS over sites 1.54 dB with no EQ, 0.90 dB with the fit (worst 1.34); leave-one-site-out mean 0.97 (worst 1.43).

**Applied and saved to JA11 USER1 (read back after save, preset 3):** 141 Hz -2.4 Q0.56, 447 Hz +2.1 Q0.72, 2098 Hz -1.1 Q0.77, 4693 Hz -1.4 Q1.98, 8464 Hz -1.6 Q3.0. Max boost +1.4 dB (low clipping risk). Script `ja11_daybreak_chu2.py` (same as `ja11_daybreak.py` with the new band list); undo with `ja11_c7.py restore`. Not yet re-checked after replug; no listening A/B. Coupler data above ~8 kHz is unreliable (csi-zone shows -5.3 dB at 9 kHz where others show +1), so the 8.5 kHz notch is a weak guess.

## Caveats
- Approximation: coupler data, R-vs-L, one unit standing in for another; no listening A/B or re-measurement.
- +2.5 dB peak digital boost with no preamp (preamp reg `0x66` is deliberately never written); loud full-scale tracks could clip slightly.
- Revert: `restore` then `save`.

## References
- [CrinEar Daybreak on CSI-Zone squig.link](https://csi-zone.squig.link/?share=CrinEar_Daybreak)
- Protocol sources as in the [C7 doc](tanchjim-fission-ktmicro-dsp-peq-match-tin-hifi-c7.md#references)
