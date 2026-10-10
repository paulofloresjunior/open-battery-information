# Battery findings

Observations from real batteries read with `tools/obi_probe.py` on an Arduino Nano (firmware with
the `0xD0` debug command). Raw dumps are JSON files in `dumps/` (gitignored); the relevant bytes are
copied below so this file stands on its own.

Sample size is small (10 packs, 8 with a chip). Anything marked **hypothesis** is a pattern that fits
every pack seen so far, not a confirmed meaning.

Since 2026-10-05 this file also merges what other projects derived from OBI found (see
[Sources](#sources-and-licenses)). Their facts were re-checked against our dumps where possible:
**checked** = holds on our packs, **unchecked** = we have no data either way, **diverges** = our packs
show something else. A divergence doesn't make the claim wrong: it may hold for packs, chargers or
firmware revisions we don't have. Those claims are kept in
[Claims we couldn't confirm](#claims-we-couldnt-confirm) for future reference.

## Byte numbering

Offsets are into the **payload**, i.e. the firmware response without its 2-byte header
(`cmd | rsp_len`). The web UI indexes the full response, so its offsets are **payload + 2**
(web UI `response[30]` = payload `[28]` here).

- `lxt_msg` — cmd `0x33`, data `AA 00`, 40 bytes: 8-byte ROM ID + 32-byte message.
- `lxt_data` — cmd `0xCC`, data `D7 00 00 FF`, 29 bytes: voltages and temperatures.

Other projects index the 32-byte message on its own ("frame byte N" / `msg[N]` = payload N+8 here)
and often by **nybble**: nybble n lives in message byte n/2, even n = low nibble, odd n = high nibble.
So nybble 40 = low nibble of payload 28, nybble 41 = its high nibble. 8-bit fields read as "even
nybble = high digit", which is why they look nibble-swapped.

## Packs read

| Pack | Chip | Made | Cycles | Lock | Cells (V) | Notes |
|---|---|---|---|---|---|---|
| BL1460B 14.4V 6.0Ah | LXT | 29/10/2022 | 3 | unlocked | 4.065 4.065 4.067 4.068 | owner's, ~2 charges remembered; healthy |
| BL1850B 18V 5.0Ah | LXT | 30/11/2021 | 10 | unlocked | 4.009 4.003 4.011 4.009 4.003 | was locked, unlocked with the web UI "Clear errors" (`33 D9 96 A5` then `33 DA 04`); no pre-unlock dump; healthy |
| BL1840B #1 18V 4.0Ah | LXT | 19/04/2018 | 14 | unlocked | 4.027 4.034 3.666 3.666 3.666 | 0.37 V imbalance; later disassembled and cells charged individually → 4.127 4.127 4.119 4.117 4.118, cycles still 14 |
| BL1840B #2 18V 4.0Ah | LXT | 19/04/2018 | 11 | unlocked | 3.505 3.503 0.959 1.469 1.548 | 3 cells deeply discharged, not locked yet |
| BL1830 18V | F0513 | 13/11/2016 | 13 | **locked** | 3.812 3.808 3.808 0.769 0.801 | cells via F0513 commands; stored long |
| BL1815N #1 18V 1.5Ah | LXT | 15/07/2019 | 7 | **locked** | 0.856 0.000 3.987 3.978 3.737 | cell 2 dead or sense wire open |
| BL1815N #2 18V 1.5Ah | LXT | 07/10/2021 | 132 | unlocked | ~0 on all | pack 0.093 V |
| BL1815N #3 18V 1.5Ah | LXT | 07/10/2021 | 134 | **locked** | ~0 on all | pack 0.099 V; same batch as #2 |
| BL1415 14.4V (no star) | none | – | – | – | – | no presence pulse, all `FF` |
| Generic clone 18V | none | – | – | – | – | no presence pulse, all `FF` |

The same wiring read the BL1830 minutes before and after the BL1415, so the silent packs are not a
rig problem. They have no data chip on the contact wired to the Nano.

## ROM ID (payload 0–7)

```
BL1460B     16 0A 1D 64 1E 08 01 57
BL1850B     15 0B 1E 64 14 0A 06 10
BL1840B #1  12 04 13 64 05 05 01 C3
BL1840B #2  12 04 13 64 05 05 04 13
BL1830      10 0B 0D 02 00 14 01 57
BL1815N #1  13 07 0F 64 32 03 88 F3
BL1815N #2  15 0A 07 64 32 03 01 51
BL1815N #3  15 0A 07 64 32 03 41 44
```

- **Not a Dallas 1-Wire ID.** The last byte never matches the Maxim CRC8. Reads were byte-identical
  across inter-byte delays of 60–250 µs, so it is not noise. The probe therefore validates the ROM by
  consistency, not CRC.
- **Bytes 0–2 = manufacture date** as YY MM DD (decimal). This is how the web UI reads it, and the
  dates are plausible for every pack. PocketOBI/PackScope read it the same way.
- Byte 3 is `0x64` (100) on every LXT-chip pack and `0x02` on the F0513 pack. synrais uses exactly
  this to pick the protocol: **byte 3 < 100 → F0513** ("type 5"). Checked on our BL1830.
- Bytes 4–5 are the same on the three BL1815N (`32 03`) and differ between models (**hypothesis:**
  model/cell code).
- Bytes 6–7 differ between packs of the same model and date (BL1815N #2/#3, BL1840B #1/#2), so they
  act as a **serial number**. The whole ROM identifies a pack, which is how two same-model reads can
  be matched to the same physical battery. PocketOBI shows the whole ROM as the "serial".

## Message (payload 8–39)

First byte shown is payload 8; each row is 32 bytes (payload 8–39).

```
BL1460B     E1 43 30 84 1B 58 00 00 94 94 40 41 D0 70 02 0E C3 A0 8E 67 E0 C7 00 03 F1 02 0E 30 00 30 00 63
BL1850B     F1 26 BD 13 14 58 00 00 94 94 40 21 D0 80 02 0E 23 D0 8E 45 60 16 00 03 02 02 0E A0 00 50 02 33
BL1840B #2  F1 26 BD 13 14 58 00 00 94 94 40 21 D0 80 02 0A 82 D0 8E 67 60 A2 00 01 02 02 0E B0 00 A0 01 81
BL1840B #1  F1 26 BD 13 14 58 00 00 C1 C1 40 21 D0 80 02 0B 82 D0 8E 67 60 A3 00 01 02 02 0E E0 00 A0 04 E1
BL1830      F1 26 BD 13 14 58 00 00 B1 B1 40 21 D0 80 02 0B C1 D0 8E 67 9F 3E 00 21 D1 02 0E D0 00 A0 02 73
BL1815N #1  41 43 CB 95 1A 68 00 00 C1 C1 40 41 01 E0 02 03 F0 D0 8E BE 5F 58 00 21 C1 02 0E 70 00 30 02 93
BL1815N #2  41 43 CB 95 1A 68 00 00 C1 C1 40 41 01 E0 02 03 F0 D0 8E BE A0 B7 00 63 01 02 0E 48 00 E7 00 29
BL1815N #3  41 43 CB 95 1A 68 00 00 C1 C1 40 41 01 E0 02 03 F0 D0 8E BE 5F 58 00 63 11 12 0E 68 00 18 00 A9
```

| Payload | Meaning | Status |
|---|---|---|
| 8 | family byte. synrais: `F1` newer, `50` older | **checked** for `F1` (BL18xxB and the F0513 BL1830). Ours also show `41` (BL1815N) and `E1` (BL1460B), which synrais doesn't list |
| 9–12 | factory variant. synrais: `26 BD 13 14` = China (Murata cells), `36 B6 C3 18` = Vietnam (Samsung) | BL1830/40B/50B carry the China value. BL1815N `43 CB 95 1A` and BL1460B `43 30 84 1B` are variants nobody has labelled |
| 13 | synrais: constant `58` | **diverges:** `68` on all BL1815N |
| 14–15 | `00 00` | checked |
| 16–17 | always a repeated pair (`C1 C1`, `94 94`, `74 74`, `24 24`, `B1 B1`). Rewritten by Clear errors (`C1`→`74`), by disassembly + per-cell charging (`C1`→`94`), and by a plain charge (`94`→`24`) | **hypothesis:** part of a last-charge record. Not a checksum (the checksums are known now and these bytes are *inside* CS1's range). synrais: writing other values here gave failure code 3 and corrupt checksums after a power cycle, so never write them |
| 18 | `40` | constant on all packs |
| 19 | battery type, nibble-swapped: 18 on BL18xxB/BL1830, 20 on BL1815N **and** BL1460B | meaning open: a 14.4V and an 18V pack share 20, so it isn't the cell count (see claims below) |
| 20 | synrais: variant (`D0` China, `01` Vietnam) | `01` on BL1815N |
| 21, 22 | synrais: constants `80`, `02` | 22 checked; 21 **diverges** (`70` BL1460B, `E0` BL1815N) |
| 24 | capacity, nibble-swapped, in 0.1 Ah (`F0`→1.5, `82`→4.0, `23`→5.0, `C3`→6.0) | **confirmed**. The BL1830's 2.8 Ah is a real capacity code: rosvall lists "BL1830B: 28 or 30". PocketOBI/PackScope also accept a whole-Ah format (raw 1–8 when the swapped value is > 60) that none of our packs use |
| 25 low nybble (nybble 34) | **charger lock**: synrais found chargers refuse the pack when it isn't 0 (200+ tests on a BL1860B) | `0` on all our packs, locked ones included. Our locks are the other kind (below) |
| 25 high nybble | rosvall: part of a "flags" byte | `D` everywhere except BL1460B (`A`) |
| 26 | `8E` | constant on all packs |
| 27 | **model/variant code**, fixed at the factory (rosvall/synrais "status code"): `67` = BL1860B/BL1830B China, `45` = BL1850B China, `1B` = BL1850B Vietnam | **checked** as "not touched by Clear errors, constant per model". `BE` (BL1815N) is new to them |
| 28 low nybble (nybble 40) | **failure code**: 0 = OK, non-zero = locked | **confirmed** (same rule as the web UI). We only saw `F`; PackScope saw `3` on a locked BL1850B |
| 28 high nybble (nybble 41) | **CS0** = sum of nybbles 0–15 (payload 8–15), low 4 bits | **checked** on every unlocked pack |
| 29 low / high (nybbles 42 / 43) | **CS1** = sum of nybbles 16–31 (payload 16–23); **CS2** = sum of nybbles 32–40 (payload 24–27 + the failure code) | **checked**. Explains why 29 changes on charge (16–17 are rewritten) and on Clear errors (failure code + 16–17) |
| 30 | synrais: bit 2 of nybble 44 = cell-failure flag | `00` on all our packs. **Writing `FF` here made the BMS go silent** (synrais) |
| 31 | bits 1–3 of nybble 46 = **damage rating 0–7** (rosvall/synrais; < 3 = full health, 7 = none) | **fits our data:** `01`→`03` (0→1) on BL1840B #1 after the full discharge + charge; `63` = 1 on the 130-cycle BL1815N |
| 32 | overdischarge index, nibble-swapped. synrais/BTC04: `% = 160 − 5x` | 28–32 on the other packs, **16/17** on the two 0 V BL1815N (→ 80/75 %). Didn't change across our charges and discharges. Formula **unchecked** |
| 33 | overload index, nibble-swapped. synrais/BTC04: `% = 5x − 160` | 32–33 on our packs (≈ 0 %). Formula **unchecked** |
| 34–35 | charge count: 13 bits, nybbles 52 (bit 0 only), 53, 54, 55 | **confirmed:** went 14 → 15 after one full charge through the BMS; 3 on a pack the owner charged ~2–3 times. Charging cells directly (bypassing the BMS) does not increment it. The 13th bit comes from synrais; ours never use it |
| 36–37 | second counter, same encoding as 34–35 (`00 A0` = 10, `00 B0` = 11) | **hypothesis:** full-charge count. Always ≤ charge count on all 8 chip packs (3/3, 11/15, 5/10, 126/132…); went 10 → 11 together with the charge count on a full discharge + full charge. synrais: "runtime, unknown; the BMS accepts any value" |
| 38 | `00`–`05`; `04` → `05` on one charge, `05` → `04` on the next | **not a counter** (it went down). Updated on charge, not on discharge. Unknown to everyone |
| 39 low / high (nybbles 62 / 63) | **AUX0** = sum of nybbles 44–47 (payload 30–31); **AUX1** = sum of nybbles 48–61 (payload 32–38) | **checked** on all packs, locked ones included. Explains why 39 changes with the counters but not on Clear errors |

### Checksums and the lock

A checksum is the low nibble of the sum of the nybbles it covers. The probe checks all five
(`checksums`, `lock_cause` in the decoded output).

**Our locked packs (BL1815N #1, #3, BL1830) all have the failure code at `F` *and* CS0, CS1 and CS2
written as the bitwise NOT of the correct value.** AUX0/AUX1 stay correct.

| Pack | CS0 stored / calc | CS1 | CS2 |
|---|---|---|---|
| BL1815N #1, #3 | 5 / A | 8 / 7 | 5 / A |
| BL1830 | 9 / 6 | E / 1 | 3 / C |

So the BMS flags its own lock by breaking the checksums on purpose. rosvall notes that the BTC04
checker treats bad checksums (or nybbles 40–43 = `FFFF`) as a broken pack, and that test mode breaks
them too while it's active.

There are two different locks:

1. **BMS lock** (ours): failure code ≠ 0 + inverted CS0–CS2. Clear errors (test mode, `DA 04`) undoes
   it: the BMS zeroes the failure code, recomputes the checksums and rewrites 16–17 itself.
2. **Charger lock** (synrais): nybble 34 ≠ 0. synrais says chargers check only nybble 34, CS0 and
   CS2, and that `DA 04` doesn't clear it; it needs a frame write (below).

## Before/after Clear errors (BL1815N #1)

Same pack read, unlocked with the web UI "Clear errors" (`33 D9 96 A5`, `33 DA 04`), read again
about 2 minutes later. Only 4 message bytes changed:

| Payload | Before | After |
|---|---|---|
| 16–17 | `C1 C1` | `74 74` |
| 28–29 | `5F 58` | `A0 B3` |

Everything else, including byte 27 (`BE`) and the charge count, stayed the same. 28–29 is now fully
explained: the failure code went `F`→`0` and CS0/CS1/CS2 went from inverted to correct (CS1 changed
value too, because 16–17 are in its range). The pack has a cell at 0 V and cell 1 dropped
0.856 → 0.837 → 0.783 V over ~35 min at rest (self-discharging), so the lock was justified.
Unlocking only clears the flag; it does not fix the cause.

## Full discharge + full charge (BL1840B #1)

After the per-cell recovery, the owner fully discharged the pack in use and fully charged it
on the Makita charger. Cells went to 4.087 4.086 4.080 4.080 4.081 (7 mV spread), so the recovery
held. Message bytes that changed: 31 `01`→`03` (damage rating 0→1), 35 `E0`→`F0` (charge count
14→15), 37 `A0`→`B0` (second counter 10→11), 38 `04`→`05`, 39 `E1`→`13` (AUX1 follows the counters).

A full discharge in use afterwards changed **no** message byte, so the counters update on charge.
It also exposed the real weak cells. Spread was 7 mV full and 363 mV empty: 3.087 3.136 3.448
3.446 3.450. Cells 1–2 have less capacity: they sat slightly high when full, and in the first
read (partial charge) they were at ~4.03 V while 3–5 were at 3.666. They limit the pack's runtime.
**Judge balance at low state of charge.** A full pack hides capacity mismatch, because the
charger tops every cell to the same voltage.

The BMS saw it too: the "real capacity" in `lxt_data` (below) went 3800 → 3440 mAh after the
recovery cycle and 3440 → 3080 mAh after this charge.

The next charge, from that empty state, changed: 16–17 `94 94`→`24 24`, 29 `A3`→`A5` (CS1 follows
16–17), 35 (charge count 15→16), 37 (second counter 11→12), 38 `05`→`04`, 39 `13`→`33`. Spread when
full: 10 mV, with cells 1–2 slightly high again. So 16–17 and 38 are rewritten on every charge; 29
and 39 just follow as checksums. Both charges here started from empty, so they can't tell "full
charge" from "any charge" for the second counter. A partial charge would.

## Live data (`lxt_data`, LXT chip only)

| Payload | Meaning | Status |
|---|---|---|
| 0–1 | pack voltage, mV, u16 LE | confirmed |
| 2–11 | cells 1–5, mV, u16 LE; 4-cell 14.4V packs report cell 5 as `0` | confirmed |
| 12–13 | ~1312–1328 on BL18xx, 6216 BL1460B, 28799 BL1850B | unknown |
| 14–15, 16–17 | temperatures, **1/10 K**, u16 LE (`°C = raw/10 − 273.15`) | see below |
| 21–22 | state of charge, u16 LE, `/256` % (synrais) | **checked:** BL1840B #1 0.2 % empty, 88.9 % after the charge, 43.6 % on a partial read; 0 % on the 0 V BL1815N |
| 23–24 | "real capacity", mAh, u16 LE (synrais) | **checked:** BL1460B 5735/6000, BL1850B 4799/5000, BL1815N 1211–1296/1500, BL1840B #2 3765, BL1840B #1 3800 → 3440 → 3080 |

**Temperature unit.** This file and the probe used to read 1/100 °C, which put every pack at
29.7–30.5 °C on every day, even straight off the charger. rosvall (BTC04 traces), PocketOBI and
PackScope all read 1/10 K (SBS convention), which gives 23.6–31.4 °C on the same raw values and
moves the way you'd expect. The probe now uses 1/10 K and also prints `temp_raw`. **Still to prove:**
read a pack straight out of the fridge; 1/10 K puts 0 °C at raw 2731. Which sensor is a cell and
which is the board/MOSFET is unknown to everyone. PocketOBI reports a dead NTC as stuck at ~−30 °C
(raw ~2430).

The F0513 chip (BL1830) answers `FF` to `lxt_data` and `lxt_model`. Its cells and temperature come
from the per-cell commands `CC 31`..`CC 35` and `CC 52` (also 1/10 K: raw 3022 = 29.05 °C). It also
answers `FF` to every memory read below (`DC 0B`, `D4`, `D7`), so none of that data exists for it.
Its two low cells kept self-discharging at rest: 0.748/0.781 V on 2026-10-01, 0.581/0.586 V on
2026-10-10, while cells 1–3 held ~3.81 V.

Extended block (`D7 00 00 FF`, reading past byte 28; synrais' v1.6.0 test build). It answers outside
test mode on both BL1815N read; the meanings are still synrais':

| Offset | Meaning | BL1815N #1 / #2 |
|---|---|---|
| 0x1D–0x1E | target capacity, mAh | 1300 / 1418 (1.5 Ah packs) |
| 0x30 | error status | `00` / `00` |
| 0x57–0x5C | six error counters | `00 00 23 00 00 80` / `00 03 20 00 00 00` |
| 0x67–0x68 | "stability count" (SOC recalibration) | 110 / 2 |

## Commands from other projects

None of these are sent by the web UI. "Read" commands are `cmd addr_lo addr_hi len` and answer
`len` bytes followed by `06` (ACK). `D7` looks like live RAM, `D4`/`D6` like stored data.
The probe sends every LXT read here in its default run, and again inside test mode with `--testmode`.

| Command | Reply | Meaning | Source |
|---|---|---|---|
| `CC DC 0B` | 17 B, last `06` | identifies a "type 0" BMS (our LXT packs) | synrais |
| `CC DC 0A` (test mode) | 17 B, last `06` | identifies "type 2" | synrais |
| `CC D4 2C 00 02` | 3 B, last `06` | identifies "type 3" | synrais |
| `CC D4 00 00 03` | YY MM DD + ACK | **assembly** date (binary), not the ROM date. Ours: 3–4 days before the ROM date (BL1815N #1 11/07 vs 15/07/2019, #2 04/10 vs 07/10/2021) | PocketOBI |
| `CC D4 50 01 02` | u16 LE + ACK | **equals the "real capacity" in `lxt_data` 23–24** on both packs read (BL1815N #1 1211 = 1211, #2 1296 = 1296), with SoC at 0 % on both, so not state of charge. Fits synrais' "health" reading, **diverges** from PocketOBI's SoC | PocketOBI, synrais |
| `CC D4 BA 00 01` | u8 + ACK | over-discharge event count (`FF` = the D4 path didn't answer). Ours: 69 on the 0 V BL1815N #2, but 0 on BL1815N #1 despite its 0 V cell 2 | both |
| `CC D4 8D 00 07` | 7 B + ACK | packed overload counters, see below | both |
| `CC D7 19 00 04` | u32 LE + ACK | coulomb counter | synrais |
| `CC D7 61 03 02` | u16 LE + ACK | average current `(32768 − raw)/100` A | synrais, speculative |
| `CC D7 0E 00 02` | u16 LE | temperature (1/10 K) | rosvall |
| `CC D9 96 A5` | `06` | enter test mode (the web UI sends it with `33` + ROM) | all |
| `CC D9 FF FF` | `06` | **leave test mode** (the web UI never sends it) | all |
| `33 [ROM] DA 04` | 9 B | clear the error log (unlock), inside test mode | all |
| `CC F0 00` | 32 B | same frame as `AA 00`, but repeating it changes state and the BMS stops answering until ENABLE drops. It arms the frame write | rosvall, synrais |
| `33 [ROM] 0F 00` + 32 B | — | write the whole 32-byte message (after the arm) | synrais, PocketOBI |
| `33 [ROM] 55 A5` | — | commit the written message | synrais, PocketOBI |

Overload counters (`D4 8D`, bytes b0–b6): `first = b0>>6 | b1<<2`, `second = b3 | (b4&3)<<8`,
`third = b5>>4 | (b6&0x3F)<<4` (synrais). PocketOBI masks the third with `0x0F`. Both add them up.
PackScope/PocketOBI turn event counts into the Makita checker's percentages as
`round_up_to_5(events × 100 / cycles)`, "calibrated on Makita's tool"; synrais uses
`4 + 100 × events / cycles`. Other BMS types keep the same data in `D6` at other addresses
(type 2: `D6 04 05`, `D6 8D 05`, `D6 5F 05`; type 3: `D6 38 02`, `D6 09 03`, `D6 5B 03`).

**Test mode doesn't survive ENABLE dropping.** Every regular firmware command powers the BMS down
after answering, so a host can't enter test mode in one command and read in the next. PackScope
read nothing but `FF` through the OBI bridge because of this. The firmware's `0xD1` session command
keeps ENABLE high across several transactions for that (`probe --testmode`). PocketOBI also clears
errors as: test mode → 30 ms → `DA 04` → 30 ms → `CC D9 FF FF` → power cycle.

**Frame write**, as synrais does it: test mode → `CC F0 00` (arm, **once per power cycle**) →
`33 [ROM] 0F 00` + 32 bytes → `33 [ROM] 55 A5` → `CC D9 FF FF` → power cycle. The BMS stays silent
for ~3 s while it writes flash. Recompute CS0–CS2 (and AUX0/AUX1 when touching payload 30–38) or the
frame is rejected. synrais' repair zeroes nybble 34 and recomputes only CS0 and CS2, leaving the
failure code alone, so on a BMS-locked pack like ours it would leave the failure code at `F`.
Clear errors is the cleaner fix for that kind of lock. Not implemented here on purpose.

## Claims we couldn't confirm

Kept for reference. Each may come from a real measurement on packs we don't have.

| Claim | Source | What our packs show |
|---|---|---|
| Battery type (payload 19) < 13 → 4 cells, 13–29 → 5 cells, 30 → 10 cells (36V) | synrais | the 4-cell BL1460B reads 20. The rule may hold on older 14.4V packs. PocketOBI dropped its "type ≥ 30 → 36V" rule in v2.1.0 |
| Failure code 15 = real capacity < 70 % of nominal | synrais test build | BL1815N #1/#3 have code 15 with 81–86 % (real capacity 1211/1290 of 1500) |
| Failure codes 1 = overcharge/overcurrent, 3 = charge fault (fuse/MOSFET/cell > 4.37 V), 4 = ?, 5 = warning, 7 = NTC/EEPROM/imbalance > 300 mV | synrais test build | unchecked; we only saw 15. Their sub-cause decoder reads frame byte 11 (the type byte), so its details are suspect |
| Model code `A5` = dead cells | synrais | our BL1815N with dead cells keep `BE` |
| Payload 13, 25 (`D0`), 21 are universal constants | synrais | BL1815N `68`, BL1460B `A0`, BL1460B `70` / BL1815N `E0` |
| Pack voltage < 5 V = invalid read | PocketOBI | our 0.09 V BL1815N answer normally: the chip is powered from the data line |
| "The Makita BMS doesn't send a standard presence pulse" | PocketOBI | every chip pack answers reset with presence here (Nano, 5 V pull-up); the silent ones have no chip. Probably their 3.3 V setup |
| Payload 32/33 percentages (`160 − 5x`, `5x − 160`) | synrais (BTC04 types 5/6) | three BL1815N of one model give 20 %, 80 %, 75 %. Plausible for the two 0 V packs, unchecked |
| Payload 32/33 as protection thresholds (`~x>>4 × 5.33 %`, `(x&0x1F) × 5 %`) | PocketOBI, PackScope | gives 0 % on BL1460B and 80 % on healthy BL1840B, so it doesn't behave like a fixed design limit |
| CS1 doesn't matter to chargers | synrais (1 BL1860B, charger model unknown) | rosvall says the BTC04 checker does check it. May differ per charger/checker |
| `D4` reads only ACK in test mode | PackScope | **diverges:** outside test mode, every `D4`/`D7` read returned data + `06` on both BL1815N (2026-10-10). Probably their bridge setup, as with test mode itself |
| `D6 58D` / `D6 309` = latched fault marker | PocketOBI ≤ 2.1.0 | retracted by PocketOBI itself: healthy BL1850B read the same constant |
| SoH = 100 − cycles / 8.96 | PocketOBI | their own heuristic, not BMS data |
| All-`FF` frame with presence = pre-LXT HC08 chip (Freescale MC908JK3E), no cell protection, don't charge | synrais | our silent packs have no presence, so a different case |
| BL36xx ("type 6", payload 25 = 30): `CC 10 21` then `D4` → 20 B, `mV = 6000 − x/10`; `D2` → 1 B, `°C = (9323 − 40x)/100` | synrais, from BTC04 traces | unchecked, no 36V pack |
| F0513 ADC sometimes needs up to 10 reads; ENABLE must stay high between `CC 99` and `31` | synrais | our firmware keeps ENABLE high inside the `0x31`/`0x32` commands, so we never hit it |
| Old (2010–2013) packs answer the message ~1 in 3 tries, some don't answer `DC 0C`/`D7`; cells then come from `CC 31..35` after two `CC F0 00` | PocketOBI | unchecked |
| Some packs stop answering live data after a `0x33` until power-cycled | PocketOBI | our firmware power-cycles every command |

## Hardware notes from other projects

- Same timing everywhere: PocketOBI and synrais vendor the same modified OneWire as ours. synrais
  also fixed the `#undef noInterrupts`/`interrupts` lines (warnings on our ESP32 build) and added
  direct SIO register access for the RP2040.
- synrais: 4.7 kΩ pull-ups on **both** data and ENABLE (5 V on AVR, 3.3 V on RP2040/ESP), **120 Ω in
  series** on both lines to protect the GPIOs (they lost RP2040 pins), and **1 kΩ between charge +
  and B−** to wake packs in deep sleep, which don't answer 1-Wire otherwise.
- PocketOBI (ESP32-C3 at 3.3 V): their PCB uses **470 Ω** pull-ups, because at 3.3 V the pack pulls
  the data line close to the threshold with 4.7 kΩ. Ground from the main B−, not the signal pin.
  AliExpress adapters number the orange connector backwards (data on "6", ENABLE on "2").
- synrais: ENABLE low ≥ 300 ms resets the BMS; 150 ms settle after ENABLE high; 30 ms between
  commands; 100 ms off for a power cycle. Ours: 400 ms settle, 400 µs after reset.

## Gotchas

- **Web UI cell difference on 14.4V packs:** the web UI computes max−min over 5 cells, so the empty
  cell 5 (`0 V`) shows the BL1460B as ~4.07 V imbalanced when it is actually within 3 mV.
- **Packs at ~0 V still answer:** the BMS chip is powered from the data line during a read, so a
  working chip does not mean the cells are alive or even connected. Measure the main terminals.

## Open questions

- Temperature: confirm 1/10 K with a cold pack.
- Bytes 16–17: what they record, and why the value differs per pack (`74` vs `94`).
- Byte 38 and the second counter (36–37): a partial charge would tell "full charge" from "any charge".
- Payload 19 (battery type) and 25 high nybble: what they encode, given BL1460B and BL1815N share 20.
- `lxt_data` 12–13.
- `D4 0x150` = real capacity on two BL1815N: does it hold on other models (BL1840B, BL1460B)?
- Meanings of the extended `D7` block are still synrais' alone; error counters differ per pack.
- Whether non-star packs (BL1415, clone) carry anything on other contacts of the yellow terminal block.

## Sources and licenses

Facts (offsets, commands, formulas) were re-implemented here from scratch; no code was copied.

- [rosvall/makita-lxt-protocol](https://github.com/rosvall/makita-lxt-protocol): BTC04 checker traces,
  message map, checksums. Copied verbatim into synrais' repo as `Makita Battery Info.md`.
- [synrais/Makita-LXT-Battery-Monitor-Unlocker](https://github.com/synrais/Makita-LXT-Battery-Monitor-Unlocker)
  (snapshot 2026-05-15): standalone monitor/unlocker derived from OBI. Charger validation, BMS types,
  frame write, extended `D7`. **No license file** (all rights reserved): don't copy its code or text.
- [TheRepairforge/PocketOBI](https://github.com/TheRepairforge/PocketOBI) (v2.2.0): ESP32-C3 handheld
  reader. MIT up to v1.0.0, **PolyForm Noncommercial** since 2026-08-06.
- [TheRepairforge/PackScope](https://github.com/TheRepairforge/PackScope) (v1.0.2): PC companion of
  PocketOBI, talks the OBI serial framing at 115200. **PolyForm Noncommercial.**
- drakosha/makita-battery-tools (MIT) and m5din-makita, credited by PocketOBI for AUX checksums and
  payload 32/33.
