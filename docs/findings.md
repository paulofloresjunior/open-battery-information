# Battery findings

Observations from real batteries read with `tools/obi_probe.py` on an Arduino Nano (firmware with
the `0xD0` debug command). Raw dumps are JSON files in `dumps/` (gitignored); the relevant bytes are
copied below so this file stands on its own.

Sample size is small (8 packs, 6 with a chip). Anything marked **hypothesis** is a pattern that fits
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
| BL1840B 18V 4.0Ah | LXT | 19/04/2018 | 14 | unlocked | 4.027 4.034 3.666 3.666 3.666 | 0.37 V imbalance |
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
BL1840B     12 04 13 64 05 05 01 C3
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

## Message (payload 8–39)

First byte shown is payload 8; each row is 32 bytes (payload 8–39).

```
BL1460B     E1 43 30 84 1B 58 00 00 94 94 40 41 D0 70 02 0E C3 A0 8E 67 E0 C7 00 03 F1 02 0E 30 00 30 00 63
BL1840B     F1 26 BD 13 14 58 00 00 C1 C1 40 21 D0 80 02 0B 82 D0 8E 67 60 A3 00 01 02 02 0E E0 00 A0 04 E1
BL1830      F1 26 BD 13 14 58 00 00 B1 B1 40 21 D0 80 02 0B C1 D0 8E 67 9F 3E 00 21 D1 02 0E D0 00 A0 02 73
BL1815N #1  41 43 CB 95 1A 68 00 00 C1 C1 40 41 01 E0 02 03 F0 D0 8E BE 5F 58 00 21 C1 02 0E 70 00 30 02 93
BL1815N #2  41 43 CB 95 1A 68 00 00 C1 C1 40 41 01 E0 02 03 F0 D0 8E BE A0 B7 00 63 01 02 0E 48 00 E7 00 29
BL1815N #3  41 43 CB 95 1A 68 00 00 C1 C1 40 41 01 E0 02 03 F0 D0 8E BE 5F 58 00 63 11 12 0E 68 00 18 00 A9
```

| Payload | Meaning | Confidence |
|---|---|---|
| 8–13 | identical across the three BL1815N; BL1830 and BL1840B share another value | **hypothesis:** model/family constant |
| 24 | capacity, nibble-swapped, in 0.1 Ah (`F0`→1.5, `82`→4.0, `C3`→6.0) | confirmed on LXT packs; BL1830 decodes to 2.8 Ah (see open questions) |
| 27 | `0x67` on BL1830/BL1840B/BL1460B, `0xBE` on all BL1815N, locked or not | **does not track lock or faults.** The web UI labels it "Status code", but it follows the model |
| 28 low nibble | `F` = locked, `0` = unlocked | matches all 6 packs (same rule the web UI uses) |
| 28–29 | `5F 58` on both locked BL1815N despite different faults; `9F 3E` on locked BL1830 | **hypothesis:** lock-reason record |
| 34–35 | charge count: nibble-swap both, big-endian, low 12 bits | plausible: 3 on a pack the owner charged ~2–3 times |

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
- Meaning of payload 28–29 beyond the lock nibble: more locked packs with known faults are needed.
- `lxt_data` bytes 12–13 (`20 05` on all BL1815N, `2C 05` BL1840B, `48 18` BL1460B) and 18–28.
- Whether non-star packs (BL1415, clone) carry anything on other contacts of the yellow terminal block.
