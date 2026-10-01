"""Probe tool for batteries the OBI-1 web UI can't read yet.

Talks to the ArduinoOBI firmware over serial, runs the same READ sequences the web UI
uses (js/modules/makita_lxt.js in openbatteryinformation.github.io) plus a few low-level
diagnostics, and saves everything as JSON so dumps from a working battery and an unknown
one can be compared byte by byte.

Read-only by default: commands that change the battery state (test mode, LEDs, clear
errors) are deliberately absent. `raw` sends arbitrary bytes and asks for confirmation.

Usage:
    python tools/obi_probe.py ports
    python tools/obi_probe.py probe --port COM9 --label BL1415
    python tools/obi_probe.py raw --port COM9 --write 33 --read 8
    python tools/obi_probe.py compare dumps/a.json dumps/b.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol

BAUD_RATE = 9600
# Opening the port pulses DTR, which reboots the Nano; the web UI waits the same 2 s.
BOOT_WAIT_S = 2.0
# Every command holds ENABLE high for 400 ms before talking to the battery.
RESPONSE_TIMEOUT_S = 3.0

FRAME_START = 0x01
CMD_VERSION = 0x01
CMD_DEBUG_RAW = 0xD0
DEBUG_FLAG_RESET = 0x01
# The firmware's rsp buffer is 255 bytes, 2 of them are the response header.
MAX_RSP_LEN = 253
# Timing used by the regular firmware commands.
DEFAULT_POST_RESET_US = 400
DEFAULT_INTER_BYTE_US = 90

DUMPS_DIR = Path(__file__).resolve().parent.parent / "dumps"


class SerialPort(Protocol):
    def write(self, payload: bytes) -> int | None: ...
    def read(self, size: int) -> bytes: ...
    def reset_input_buffer(self) -> None: ...
    def close(self) -> None: ...


class ObiError(Exception):
    pass


def build_frame(cmd: int, data: bytes, rsp_len: int) -> bytes:
    if len(data) > 255:
        raise ObiError(f"data has {len(data)} bytes; the frame length field holds at most 255")
    if not 0 <= rsp_len <= MAX_RSP_LEN:
        raise ObiError(f"rsp_len={rsp_len}; expected 0..{MAX_RSP_LEN}")
    return bytes([FRAME_START, len(data), rsp_len, cmd]) + data


def crc8_maxim(payload: bytes) -> int:
    """Dallas/Maxim 1-Wire CRC8 (poly 0x31 reflected), same as OneWire::crc8."""
    crc = 0
    for byte in payload:
        for _ in range(8):
            mix = (crc ^ byte) & 0x01
            crc >>= 1
            if mix:
                crc ^= 0x8C
            byte >>= 1
    return crc


def u16le(payload: bytes, offset: int) -> int:
    return payload[offset] | (payload[offset + 1] << 8)


def nibble_swap(byte: int) -> int:
    return ((byte & 0xF0) >> 4) | ((byte & 0x0F) << 4)


def hex_dump(payload: bytes) -> str:
    return " ".join(f"{b:02X}" for b in payload)


@dataclass
class DebugResult:
    idle_level: int
    presence: int | None  # None when the reset was skipped
    read: bytes


class ObiLink:
    def __init__(self, port: SerialPort, timeout_s: float = RESPONSE_TIMEOUT_S):
        self._port = port
        self._timeout_s = timeout_s

    def request(self, cmd: int, data: bytes, rsp_len: int) -> bytes:
        """Sends one frame and returns the payload (without the cmd/len header)."""
        self._port.reset_input_buffer()
        self._port.write(build_frame(cmd, data, rsp_len))
        header = self._read_exact(2)
        if len(header) < 2:
            raise ObiError(f"no response to cmd 0x{cmd:02X} within {self._timeout_s}s")
        if header[0] != cmd:
            raise ObiError(f"response echoes cmd 0x{header[0]:02X}; expected 0x{cmd:02X}")
        payload = self._read_exact(header[1])
        if len(payload) != header[1]:
            raise ObiError(f"cmd 0x{cmd:02X}: got {len(payload)} of {header[1]} payload bytes")
        return payload

    def version(self) -> str:
        payload = self.request(CMD_VERSION, b"", 3)
        return ".".join(str(b) for b in payload)

    def debug_raw(
        self,
        write: bytes,
        read_len: int,
        reset: bool = True,
        post_reset_us: int = DEFAULT_POST_RESET_US,
        inter_byte_us: int = DEFAULT_INTER_BYTE_US,
    ) -> DebugResult:
        if not 0 <= post_reset_us <= 2550 or post_reset_us % 10:
            raise ObiError(f"post_reset_us={post_reset_us}; expected a multiple of 10 in 0..2550")
        if not 0 <= inter_byte_us <= 255:
            raise ObiError(f"inter_byte_us={inter_byte_us}; expected 0..255")
        rsp_len = read_len + 2
        flags = DEBUG_FLAG_RESET if reset else 0
        data = bytes([flags, post_reset_us // 10, inter_byte_us]) + write
        payload = self.request(CMD_DEBUG_RAW, data, rsp_len)
        if len(payload) == 0:
            raise ObiError(
                "firmware ignored cmd 0xD0 (debug); flash the firmware from branch feature/debug-probe"
            )
        if len(payload) != rsp_len:
            raise ObiError(f"debug cmd returned {len(payload)} bytes; expected {rsp_len}")
        presence = None if payload[1] == 0xFF else payload[1]
        return DebugResult(idle_level=payload[0], presence=presence, read=payload[2:])

    def _read_exact(self, size: int) -> bytes:
        deadline = time.monotonic() + self._timeout_s
        received = b""
        while len(received) < size and time.monotonic() < deadline:
            received += self._port.read(size - len(received))
        return received


# --- what the web UI sends during a normal "Read battery" -------------------------------
# (cmd, data, rsp_len). Kept identical so a dump here matches what the site would see.


@dataclass(frozen=True)
class KnownRead:
    name: str
    cmd: int
    data: bytes
    rsp_len: int
    note: str


KNOWN_READS: tuple[KnownRead, ...] = (
    KnownRead("lxt_msg", 0x33, bytes([0xAA, 0x00]), 0x28,
              "ROM ID (8) + 32-byte battery message; first thing the site reads"),
    KnownRead("lxt_model", 0xCC, bytes([0xDC, 0x0C]), 0x10, "ASCII model on star batteries"),
    KnownRead("lxt_data", 0xCC, bytes([0xD7, 0x00, 0x00, 0xFF]), 0x1D,
              "pack/cell voltages and temperatures (u16le)"),
    KnownRead("f0513_model", 0x31, b"", 0x02,
              "older F0513 chip; firmware sends CC 99 (test mode) first, like the site"),
    KnownRead("f0513_version", 0x32, b"", 0x02, "older F0513 chip"),
    KnownRead("f0513_vcell1", 0xCC, bytes([0x31]), 0x02, "F0513 cell 1 mV (u16le)"),
    KnownRead("f0513_vcell2", 0xCC, bytes([0x32]), 0x02, "F0513 cell 2 mV (u16le)"),
    KnownRead("f0513_vcell3", 0xCC, bytes([0x33]), 0x02, "F0513 cell 3 mV (u16le)"),
    KnownRead("f0513_vcell4", 0xCC, bytes([0x34]), 0x02, "F0513 cell 4 mV (u16le)"),
    KnownRead("f0513_vcell5", 0xCC, bytes([0x35]), 0x02, "F0513 cell 5 mV (u16le)"),
    KnownRead("f0513_temp", 0xCC, bytes([0x52]), 0x02, "F0513 temperature, 1/100 C (u16le)"),
)

INTER_BYTE_SWEEP_US = (60, 90, 120, 180, 250)


@dataclass
class Step:
    name: str
    request: str
    ok: bool
    response: str = ""
    error: str = ""
    decoded: dict[str, str] = field(default_factory=dict)


def decode_rom(rom: bytes) -> dict[str, str]:
    crc_ok = crc8_maxim(rom[:7]) == rom[7]
    return {
        "family_code": f"0x{rom[0]:02X}",
        "serial": hex_dump(rom[1:7]),
        "crc": "OK" if crc_ok else f"FAIL (calc 0x{crc8_maxim(rom[:7]):02X}, got 0x{rom[7]:02X})",
        "all_ff": str(all(b == 0xFF for b in rom)),
    }


def decode_known(name: str, payload: bytes) -> dict[str, str]:
    """Interprets a payload as if the battery used the known LXT/F0513 layouts."""
    if all(b == 0xFF for b in payload):
        return {"hint": "all 0xFF = nobody pulled the line low (no answer)"}
    if all(b == 0x00 for b in payload):
        return {"hint": "all 0x00 = line held low (short, or BMS busy)"}
    if name == "lxt_msg" and len(payload) >= 40:
        decoded = decode_rom(payload[:8])
        decoded.update({
            "mfg_date_if_lxt": f"{payload[2]:02d}/{payload[1]:02d}/20{payload[0]:02d}",
            "capacity_if_lxt": f"{nibble_swap(payload[24]) / 10:.1f}Ah",
            "lock_if_lxt": "LOCKED" if payload[28] & 0x0F else "UNLOCKED",
            "status_if_lxt": f"0x{payload[27]:02X}",
        })
        return decoded
    if name == "lxt_model":
        return {"ascii": payload[:7].decode("ascii", errors="replace")}
    if name == "lxt_data" and len(payload) >= 18:
        cells = [u16le(payload, o) / 1000 for o in (2, 4, 6, 8, 10)]
        return {"pack_v": f"{u16le(payload, 0) / 1000:.3f}", "cells_v": str(cells),
                "temp1_c": f"{u16le(payload, 14) / 100:.2f}"}
    if name in ("f0513_model", "f0513_version"):
        # Firmware stores these 2 bytes swapped; the site renders them as "BL" + hex.
        return {"as_model": f"BL{payload[0]:X}{payload[1]:X}"}
    if len(payload) == 2:
        return {"u16le": str(u16le(payload, 0)), "as_volts": f"{u16le(payload, 0) / 1000:.3f}"}
    return {}


def run_step(name: str, request_desc: str, action: Callable[[], bytes],
             decoder: Callable[[bytes], dict[str, str]]) -> Step:
    try:
        payload = action()
    except ObiError as exc:
        return Step(name, request_desc, ok=False, error=str(exc))
    return Step(name, request_desc, ok=True, response=hex_dump(payload), decoded=decoder(payload))


def probe(link: ObiLink, log: Callable[[str], None]) -> dict[str, object]:
    report: dict[str, object] = {"timestamp": datetime.now().isoformat(timespec="seconds")}
    report["firmware"] = link.version()
    log(f"firmware {report['firmware']}")

    steps: list[Step] = []

    def record(step: Step) -> None:
        steps.append(step)
        status = "ok " if step.ok else "ERR"
        log(f"[{status}] {step.name:<16} {step.response or step.error}")
        for key, value in step.decoded.items():
            log(f"        {key}: {value}")

    presence = link.debug_raw(write=b"", read_len=0)
    report["line"] = {"idle_level": presence.idle_level, "presence": presence.presence}
    log(f"idle line level={presence.idle_level} (1 = pulled up OK), "
        f"presence pulse={'YES' if presence.presence else 'NO'}")

    rom_steps = []
    for inter_byte_us in INTER_BYTE_SWEEP_US:
        step = run_step(
            f"rom@{inter_byte_us}us", f"D0 reset + 33, read 8, {inter_byte_us}us",
            lambda us=inter_byte_us: link.debug_raw(write=bytes([0x33]), read_len=8,
                                                    inter_byte_us=us).read,
            decode_rom,
        )
        record(step)
        rom_steps.append(step)

    for known in KNOWN_READS:
        record(run_step(
            known.name, f"{known.cmd:02X} {hex_dump(known.data)} rsp_len={known.rsp_len}",
            lambda k=known: link.request(k.cmd, k.data, k.rsp_len),
            lambda payload, k=known: decode_known(k.name, payload),
        ))

    report["steps"] = [asdict(s) for s in steps]
    report["summary"] = summarize(presence, rom_steps, steps)
    for line in report["summary"]:
        log(f">> {line}")
    return report


def summarize(presence: DebugResult, rom_steps: list[Step], steps: list[Step]) -> list[str]:
    if presence.idle_level == 0:
        return ["data line is LOW at idle: check wiring/pull-up, or the BMS is holding the bus"]
    if not presence.presence:
        return ["no presence pulse: likely no 1-Wire chip (or not on this contact/pin)"]
    lines = []
    good_rom = [s.name for s in rom_steps if s.decoded.get("crc") == "OK"]
    if good_rom:
        lines.append(f"valid 1-Wire ROM read at: {', '.join(good_rom)}")
    else:
        lines.append("chip answers reset but ROM CRC never matched: maybe not standard 1-Wire")
    answered = [s.name for s in steps
                if s.ok and "hint" not in s.decoded and not s.name.startswith("rom@")]
    lines.append(f"known commands with real data: {', '.join(answered) or 'none'}")
    return lines


def compare(path_a: Path, path_b: Path) -> list[str]:
    def responses(path: Path) -> dict[str, str]:
        report = json.loads(path.read_text(encoding="utf-8"))
        return {s["name"]: s["response"] or f"<{s['error']}>" for s in report["steps"]}

    left, right = responses(path_a), responses(path_b)
    lines = []
    for name in sorted(set(left) | set(right)):
        a, b = left.get(name, "<missing>"), right.get(name, "<missing>")
        marker = "  " if a == b else "!="
        lines.append(f"{marker} {name}\n     A: {a}\n     B: {b}")
    return lines


def open_link(port_name: str) -> tuple[ObiLink, SerialPort]:
    import serial  # imported lazily so tests and `compare` don't need pyserial

    port = serial.Serial(port_name, BAUD_RATE, timeout=0.2)
    time.sleep(BOOT_WAIT_S)
    return ObiLink(port), port


def parse_hex(text: str) -> bytes:
    try:
        return bytes.fromhex(text.replace(",", " "))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid hex {text!r}; expected e.g. '33' or 'CC D7 00'") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ports", help="list serial ports")

    p_probe = sub.add_parser("probe", help="run the read-only diagnostic and save a JSON dump")
    p_probe.add_argument("--port", required=True)
    p_probe.add_argument("--label", default="battery", help="name used in the dump file")

    p_raw = sub.add_parser("raw", help="send arbitrary 1-Wire bytes via the debug command")
    p_raw.add_argument("--port", required=True)
    p_raw.add_argument("--write", type=parse_hex, default=b"", help="hex bytes to write")
    p_raw.add_argument("--read", type=int, default=0, help="bytes to read back")
    p_raw.add_argument("--no-reset", action="store_true")
    p_raw.add_argument("--post-reset-us", type=int, default=DEFAULT_POST_RESET_US)
    p_raw.add_argument("--inter-byte-us", type=int, default=DEFAULT_INTER_BYTE_US)
    p_raw.add_argument("--yes", action="store_true", help="skip the confirmation prompt")

    p_cmp = sub.add_parser("compare", help="diff two probe dumps")
    p_cmp.add_argument("a", type=Path)
    p_cmp.add_argument("b", type=Path)

    args = parser.parse_args(argv)

    if args.command == "ports":
        from serial.tools import list_ports
        for info in list_ports.comports():
            print(f"{info.device:<8} {info.description}")
        return 0

    if args.command == "compare":
        print("\n".join(compare(args.a, args.b)))
        return 0

    if args.command == "raw" and not args.yes:
        print(f"About to write [{hex_dump(args.write)}] to the battery. Unknown commands can "
              "change BMS state (test mode, lock, EEPROM). Continue? [y/N] ", end="")
        if input().strip().lower() != "y":
            return 1

    link, port = open_link(args.port)
    try:
        if args.command == "raw":
            if args.read > MAX_RSP_LEN - 2:
                raise ObiError(f"--read {args.read}; expected at most {MAX_RSP_LEN - 2}")
            result = link.debug_raw(args.write, args.read, reset=not args.no_reset,
                                    post_reset_us=args.post_reset_us,
                                    inter_byte_us=args.inter_byte_us)
            print(f"idle={result.idle_level} presence={result.presence} read: {hex_dump(result.read)}")
            return 0

        report = probe(link, print)
        report["label"] = args.label
        DUMPS_DIR.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = DUMPS_DIR / f"{args.label}_{stamp}.json"
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"saved {out}")
        return 0
    except ObiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        port.close()


if __name__ == "__main__":
    sys.exit(main())
