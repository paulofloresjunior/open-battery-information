# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Arduino firmware only (`ArduinoOBI/`) for the Open Battery Information interface: it turns an Arduino
Uno/Nano or ESP32-C3 into a USB-serial ↔ 1-Wire bridge for reading (and unlocking) Makita battery BMSs.
The old Python/Tkinter desktop app was removed (last version at tag `v0.2.3`). The host-side UI now
lives in a **separate repo** (`OpenBatteryInformation/openbatteryinformation.github.io`) and talks to
this firmware over Web Serial — so the serial protocol below is a contract with code that is not here.

## Build / flash (PlatformIO, run from `ArduinoOBI/`)

```bash
pio run -e uno                     # default env; also: nano, nano_new, esp32-c3-devkitm-1
pio run -e uno -t upload           # flash
pio device monitor -b 9600         # serial monitor (firmware uses 9600 baud)
```

There are no firmware tests (`test/` only holds the PlatformIO placeholder README) and no linter.
PlatformIO is installed in the repo-local `.venv` (`.venv/Scripts/pio` on Windows). The user's board
is an Arduino Nano clone (CH340) with the **old** bootloader → use env `nano`, not `nano_new`.

## Probe tool (`tools/obi_probe.py`)

Python host tool for reverse-engineering batteries the web UI can't read. It replays the web UI's
read commands (copied from `js/modules/makita_lxt.js` in the web UI repo), uses `0xD0` for
presence/ROM consistency/timing sweeps, and saves JSON dumps to `dumps/` (gitignored). The ROM ID
identifies a physical pack, so `probe` looks up earlier dumps of the same pack and prints what
changed. Diffs re-decode from raw bytes, because older dumps stored different decoded keys.
Byte meanings found so far live in `docs/findings.md`.

```bash
.venv/Scripts/python tools/obi_probe.py probe --port COM9 --label BL1415
.venv/Scripts/python tools/obi_probe.py compare dumps/a.json dumps/b.json
.venv/Scripts/python -m unittest discover tools                       # all tests
.venv/Scripts/python -m unittest discover tools -k DecodeTests        # filter by name
```

`probe` must stay read-only: LEDs (`33 DA ..`), clear-errors (`33 DA 04`) and frame writes
(`CC F0 00` / `33 0F 00` / `33 55 A5`) change BMS state and are intentionally excluded; arbitrary
bytes go through `raw`, which asks for confirmation. The one exception is `probe --testmode`
(asks for confirmation): it enters test mode, repeats the `MEMORY_READS` (`D4`/`D7`/`DC` reads
taken from other projects) and leaves with `CC D9 FF FF`, all in one `0xD1` session.

The `lxt_msg` decode (checksums CS0–CS2/AUX0–1, failure code, lock cause, counters) follows the
nybble map in `docs/findings.md`; tests use real dumps as fixtures, so keep them in sync. Temperatures
are 1/10 K. Facts taken from PocketOBI/PackScope (PolyForm Noncommercial) and synrais (no license)
must be re-implemented, never copied — see "Sources and licenses" in `docs/findings.md`.

- **Versioning:** `scripts/get_version.py` (pre-script for every env) reads the latest git tag
  (`vX.Y.Z`) via `git describe --tags --abbrev=0` and injects `ARDUINO_OBI_VERSION_{MAJOR,MINOR,PATCH}`.
  No tag / no git → `0.0.0`. Don't hardcode versions in `main.cpp`.
- **ESP32-C3:** pins come from `build_flags` in `platformio.ini` (`ESP_BUILD`, `ESP_EN_PIN=0`,
  `ESP_OW_PIN=1`); AVR builds use hardcoded `ONEWIRE_PIN 6` / `ENABLE_PIN 8`. Pull-ups on ESP must go
  to 3.3V, not 5V.
- **CI release:** `.github/workflows/firmware.yml` runs on a published GitHub release (or manual
  dispatch), builds `uno`, `nano_new` and `esp32-c3-devkitm-1`, merges the ESP image with
  `esptool merge_bin` (bootloader 0x0, partitions 0x8000, app 0x10000) and uploads assets to the
  release. The web UI's browser flasher consumes these release assets (`uno.hex`, `esp32.bin`), so
  renaming them breaks flashing.

## Firmware architecture (`ArduinoOBI/src/main.cpp`)

Single-file, polling `loop()` → `read_usb()`.

**Serial request frame:** `0x01 | len | rsp_len | cmd | data[len]` (processed once ≥4 bytes are
available; any other start byte is dropped). **Response:** `cmd | rsp_len | payload[rsp_len]`.
`ENABLE_PIN` is driven HIGH (+400 ms settle) around each command to power the battery's 1-Wire side.

Commands:
- `0x01` — firmware version (bytes 2–4 of response = major/minor/patch).
- `0x31` / `0x32` — send `0xCC 0x99`, wait, then issue `0x31`/`0x32` and read 2 bytes (stored
  byte-swapped into `rsp[3]`, `rsp[2]`).
- `0x33` — Read-ROM (`0x33`) then 8-byte ROM ID, then write `data`, then read. The ROM ID is written
  into the first 8 payload bytes, but only `rsp_len` bytes are transmitted, so the host's `rsp_len`
  must include those 8 bytes.
- `0xCC` — Skip-ROM (`0xCC`), write `data`, read `rsp_len` bytes.
- `0xD0` — debug/probe (not used by the web UI). `data = [flags, post_reset_delay×10µs,
  inter_byte_delay_µs, bytes to write…]`, flag bit0 = reset first. Payload =
  `[idle_line_level, presence (0xFF = no reset), rsp_len−2 bytes read…]`. `rsp_len` is clamped to 253.
- `0xD1` — session (not used by the web UI): several transactions with ENABLE held high, because
  dropping ENABLE ends BMS test mode. `data` = repeated `[flags, delay_ms, write_len, read_len,
  write…]` (flag bit0 = reset first); payload = per transaction `[presence (0xFF = no reset),
  read bytes…]`. The whole request is validated before touching the bus; malformed → `rsp_len = 0`.
- anything else → empty response (`rsp_len = 0`).

`rsp_len` is clamped so reads fit the 255-byte buffer (253 payload; 245 for `0x33`, which stores the
ROM in front). A frame whose data bytes stop arriving for 50 ms is dropped instead of blocking.

The magic delays (`delayMicroseconds(400)` after reset, `90` µs between bytes) are protocol timing for
the Makita BMS — keep them unless you have hardware to verify.

**`lib/OneWire/`** is a vendored, modified copy of PJRC OneWire (header `OneWire2.h`, class still
`OneWire`). Prefer changing `main.cpp` over this library.
