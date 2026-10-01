"""Run with: python -m unittest discover tools"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import obi_probe as obi


class FakeFirmwareSerial:
    """Emulates the ArduinoOBI serial framing: answers each frame with cmd|len|payload."""

    def __init__(self, answers: dict[int, bytes], supports_debug: bool = True):
        self.answers = answers
        self.supports_debug = supports_debug
        self.sent: list[bytes] = []
        self._pending = b""

    def write(self, payload: bytes) -> int:
        self.sent.append(payload)
        cmd, rsp_len = payload[3], payload[2]
        if cmd == obi.CMD_DEBUG_RAW and not self.supports_debug:
            self._pending = bytes([cmd, 0])
            return len(payload)
        body = self.answers.get(cmd, bytes([0xFF]) * rsp_len)[:rsp_len]
        self._pending = bytes([cmd, len(body)]) + body
        return len(payload)

    def read(self, size: int) -> bytes:
        chunk, self._pending = self._pending[:size], self._pending[size:]
        return chunk

    def reset_input_buffer(self) -> None:
        self._pending = b""

    def close(self) -> None:
        pass


# Worked example from Maxim Application Note 27 (CRC8 = 0xA2).
VALID_ROM = bytes.fromhex("021CB801000000A2")


class FramingTests(unittest.TestCase):
    def test_build_frame_layout(self):
        self.assertEqual(obi.build_frame(0xCC, b"\xD7\x00", 0x1D), bytes([1, 2, 0x1D, 0xCC, 0xD7, 0]))

    def test_build_frame_rejects_oversized_response(self):
        with self.assertRaises(obi.ObiError):
            obi.build_frame(0xD0, b"", 254)

    def test_crc8_matches_known_rom(self):
        self.assertEqual(obi.crc8_maxim(VALID_ROM[:7]), VALID_ROM[7])


class LinkTests(unittest.TestCase):
    def test_version(self):
        link = obi.ObiLink(FakeFirmwareSerial({obi.CMD_VERSION: bytes([0, 3, 1])}), timeout_s=0.1)
        self.assertEqual(link.version(), "0.3.1")

    def test_debug_raw_encodes_timing_and_splits_payload(self):
        fake = FakeFirmwareSerial({obi.CMD_DEBUG_RAW: bytes([1, 1]) + VALID_ROM})
        result = obi.ObiLink(fake, timeout_s=0.1).debug_raw(b"\x33", 8, inter_byte_us=120)
        self.assertEqual(fake.sent[0], bytes([1, 4, 10, 0xD0, 0x01, 40, 120, 0x33]))
        self.assertEqual((result.idle_level, result.presence, result.read), (1, 1, VALID_ROM))

    def test_debug_raw_on_old_firmware_explains_how_to_fix(self):
        link = obi.ObiLink(FakeFirmwareSerial({}, supports_debug=False), timeout_s=0.1)
        with self.assertRaisesRegex(obi.ObiError, "flash the firmware"):
            link.debug_raw(b"", 0)

    def test_silent_board_times_out(self):
        class DeadSerial(FakeFirmwareSerial):
            def read(self, size: int) -> bytes:
                return b""

        with self.assertRaisesRegex(obi.ObiError, "no response"):
            obi.ObiLink(DeadSerial({}), timeout_s=0.05).version()


class DecodeTests(unittest.TestCase):
    def test_rom_crc_ok_and_fail(self):
        self.assertEqual(obi.decode_rom(VALID_ROM)["crc"], "OK")
        self.assertTrue(obi.decode_rom(VALID_ROM[:7] + b"\x00")["crc"].startswith("FAIL"))

    def test_all_ff_is_flagged_as_no_answer(self):
        self.assertIn("no answer", obi.decode_known("lxt_data", b"\xFF" * 29)["hint"])

    def test_lxt_data_offsets_match_web_ui(self):
        # Web UI reads pack at response[2], cell1 at [4], temp at [16]; payload drops 2 bytes.
        payload = bytearray(29)
        payload[0:2] = (18000).to_bytes(2, "little")
        payload[2:4] = (3600).to_bytes(2, "little")
        payload[14:16] = (2550).to_bytes(2, "little")
        decoded = obi.decode_known("lxt_data", bytes(payload))
        self.assertEqual(decoded["pack_v"], "18.000")
        self.assertTrue(decoded["cells_v"].startswith("[3.6,"))
        self.assertEqual(decoded["temp1_c"], "25.50")


class ProbeTests(unittest.TestCase):
    def test_no_presence_is_summarized(self):
        fake = FakeFirmwareSerial({obi.CMD_VERSION: bytes(3), obi.CMD_DEBUG_RAW: bytes([1, 0])})
        report = obi.probe(obi.ObiLink(fake, timeout_s=0.1), lambda _: None)
        self.assertIn("no presence", report["summary"][0])

    def test_compare_marks_differences(self):
        def dump(response: str) -> dict[str, object]:
            return {"steps": [{"name": "lxt_msg", "response": response, "error": ""}]}

        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp, "a.json"), Path(tmp, "b.json")
            a.write_text(json.dumps(dump("01 02")), encoding="utf-8")
            b.write_text(json.dumps(dump("01 03")), encoding="utf-8")
            self.assertTrue(obi.compare(a, b)[0].startswith("!="))


if __name__ == "__main__":
    unittest.main()
