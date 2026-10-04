# Battery findings

Observations from real batteries read with `tools/obi_probe.py` on an Arduino Nano (firmware with
the `0xD0` debug command). Raw dumps are JSON files in `dumps/` (gitignored); the relevant bytes are
copied below so this file stands on its own.

Sample size is small (10 packs, 8 with a chip). Anything marked **hypothesis** is a pattern that fits
every pack seen so far, not a confirmed meaning.

## Byte numbering

Offsets are into the **payload**, i.e. the firmware response without its 2-byte header
(`cmd | rsp_len`). The web UI indexes the full response, so its offsets are **payload + 2**
(web UI `response[30]` = payload `[28]` here).

- `lxt_msg` — cmd `0x33`, data `AA 00`, 40 bytes: 8-byte ROM ID + 32-byte message.
- `lxt_data` — cmd `0xCC`, data `D7 00 00 FF`, 29 bytes: voltages and temperatures.

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
  dates are plausible for every pack.
- Byte 3 is `0x64` on every LXT-chip pack and `0x02` on the F0513 pack (**hypothesis:** chip/protocol
  generation).
- Bytes 4–5 are the same on the three BL1815N (`32 03`) and differ between models (**hypothesis:**
  model/cell code).
- Bytes 6–7 differ between packs of the same model and date (BL1815N #2/#3, BL1840B #1/#2), so they
  act as a **serial number**. The whole ROM identifies a pack, which is how two same-model reads can
  be matched to the same physical battery.

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

| Payload | Meaning | Confidence |
|---|---|---|
| 8–13 | identical across the three BL1815N; BL1830, BL1840B and BL1850B share another value | **hypothesis:** model/family constant |
| 24 | capacity, nibble-swapped, in 0.1 Ah (`F0`→1.5, `82`→4.0, `23`→5.0, `C3`→6.0) | confirmed on LXT packs; BL1830 decodes to 2.8 Ah (see open questions) |
| 16–17 | always a repeated pair (`C1 C1`, `94 94`…). Rewritten by Clear errors (`C1 C1` → `74 74`), and on BL1840B #1 after disassembly + per-cell charging (`C1 C1` → `94 94`), lock unchanged | **hypothesis:** rewritten when the BMS resets (both events can restart it). Not a health flag (`94 94` also on the badly discharged BL1840B #2) and not a sum/XOR/nibble-sum checksum |
| 27 | `0x67` on BL1830/BL1840B/BL1460B, `0xBE` on all BL1815N, `0x45` on BL1850B | **not touched by Clear errors** (before/after, below), so not the lock status. Per-pack/per-model value of unknown meaning |
| 28 low nibble | `F` = locked, `0` = unlocked | matches all 7 packs (same rule the web UI uses) |
| 28–29 | locked: `5F 58` (both locked BL1815N), `9F 3E` (BL1830). Clear errors turned `5F 58` into `A0 B3` | **hypothesis:** lock record. Byte 28 after unlock is the bitwise NOT of before (`5F` → `A0`); `~9F` = `60`, the value on unlocked BL1840B/BL1850B. Byte 29 does not follow that rule |
| 31 | `01`, `03`, `21`, `63` seen; went `01` → `03` on BL1840B #1 after a full discharge + full charge | unknown, possibly flags |
| 34–35 | charge count: nibble-swap both, big-endian, low 12 bits | **confirmed:** went 14 → 15 after one full charge through the BMS; 3 on a pack the owner charged ~2–3 times. Charging cells directly (bypassing the BMS) does not increment it |
| 36–37 | second counter, same encoding as 34–35 (`00 A0` = 10, `00 B0` = 11) | **hypothesis:** full-charge count. Always ≤ charge count on all 8 chip packs (3/3, 11/15, 5/10, 126/132…); went 10 → 11 together with the charge count on a full discharge + full charge |
| 38 | `00`–`05`; went `04` → `05` after a full discharge | **weak hypothesis:** discharge-to-cutoff count. `00` on the owner's never-drained BL1460B, but also `00` on the 0 V BL1815N #2/#3 (maybe drained in storage with the BMS asleep) |
| 39 | changes with the counters (`E1` → `13`), but not when Clear errors rewrote 16–17/28–29 | unknown; not a sum/XOR of any suffix of the payload |

## Before/after Clear errors (BL1815N #1)

Same pack read, unlocked with the web UI "Clear errors" (`33 D9 96 A5`, `33 DA 04`), read again
about 2 minutes later. Only 4 message bytes changed:

| Payload | Before | After |
|---|---|---|
| 16–17 | `C1 C1` | `74 74` |
| 28–29 | `5F 58` | `A0 B3` |

Everything else, including byte 27 (`BE`) and the charge count, stayed the same. The pack has a
cell at 0 V and cell 1 dropped 0.856 → 0.837 → 0.783 V over ~35 min at rest (self-discharging),
so the lock was justified. Unlocking only clears the flag; it does not fix the cause.

## Full discharge + full charge (BL1840B #1)

After the per-cell recovery, the owner fully discharged the pack in use and fully charged it
on the Makita charger. Cells went to 4.087 4.086 4.080 4.080 4.081 (7 mV spread), so the recovery
held. Message bytes that changed: 31 `01`→`03`, 35 `E0`→`F0` (charge count 14→15), 37 `A0`→`B0`
(second counter 10→11), 38 `04`→`05`, 39 `E1`→`13`.

## Live data (`lxt_data`, LXT chip only)

| Payload | Meaning |
|---|---|
| 0–1 | pack voltage, mV, u16 LE |
| 2–11 | cells 1–5, mV, u16 LE; 4-cell 14.4V packs report cell 5 as `0` |
| 14–15, 16–17 | temperatures, 1/100 °C, u16 LE |

The F0513 chip (BL1830) answers `FF` to `lxt_data` and `lxt_model`. Its cells and temperature come
from the per-cell commands `CC 31`..`CC 35` and `CC 52` instead.

## Gotchas

- **Web UI cell difference on 14.4V packs:** the web UI computes max−min over 5 cells, so the empty
  cell 5 (`0 V`) shows the BL1460B as ~4.07 V imbalanced when it is actually within 3 mV.
- **Packs at ~0 V still answer:** the BMS chip is powered from the data line during a read, so a
  working chip does not mean the cells are alive or even connected. Measure the main terminals.

## Open questions

- BL1830 capacity decodes to 2.8 Ah, though the model is sold as 3.0 Ah. Either the F0513 message
  layout differs, or byte 24 holds a rated/measured value rather than the label capacity.
- Byte 27: unlock doesn't write it (answered by the before/after above), but its meaning is open.
- Bytes 16–17: what the unlock writes there, and why the value differs per pack (`74` vs `94`).
- Meaning of payload 28–29 beyond the lock nibble: more locked packs with known faults are needed.
- `lxt_data` bytes 12–13 (`20 05` on all BL1815N, `2C 05` BL1840B, `48 18` BL1460B) and 18–28.
- Whether non-star packs (BL1415, clone) carry anything on other contacts of the yellow terminal block.
