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
# Captured from a real BL1830 (F0513 chip): identical at every timing, yet the Maxim CRC
# doesn't match. The first version of the tool reported this as a failure.
BL1830_ROM = bytes.fromhex("100B0D0200140157")


def rom_step(name: str, rom: bytes) -> obi.Step:
    return obi.Step(name, "", ok=True, response=obi.hex_dump(rom), decoded=obi.decode_rom(rom))


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
    def test_makita_rom_crc_mismatch_is_not_treated_as_error(self):
        decoded = obi.decode_rom(BL1830_ROM)
        self.assertNotIn("hint", decoded)
        self.assertTrue(decoded["maxim_crc"].startswith("no match"))
        self.assertEqual(decoded["first_bytes_as_date"], "13/11/2016")

    def test_blank_rom_is_flagged(self):
        self.assertIn("hint", obi.decode_rom(b"\xFF" * 8))

    def test_lxt_msg_decodes_real_dumps_like_web_ui(self):
        # 40-byte lxt_msg payloads captured from the user's batteries (dumps/ on 2026-10-01).
        bl1830 = bytes.fromhex(
            "100B0D0200140157F126BD1314580000B1B14021D080020BC1D08E679F3E0021D1020ED000A00273")
        bl1840b = bytes.fromhex(
            "12041364050501C3F126BD1314580000C1C14021D080020B82D08E6760A3000102020EE000A004E1")
        decoded_1830 = obi.decode_known("lxt_msg", bl1830)
        decoded_1840b = obi.decode_known("lxt_msg", bl1840b)
        self.assertEqual(decoded_1830["charge_count_if_lxt"], "13")
        self.assertEqual(decoded_1830["lock_if_lxt"], "LOCKED")
        self.assertEqual(decoded_1840b["charge_count_if_lxt"], "14")
        self.assertEqual(decoded_1840b["capacity_if_lxt"], "4.0Ah")
        self.assertEqual(decoded_1840b["lock_if_lxt"], "UNLOCKED")

    def test_f0513_temperature_in_celsius(self):
        self.assertEqual(obi.decode_known("f0513_temp", bytes.fromhex("CE0B")), {"temp_c": "30.22"})

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

    def test_rom_identical_across_sweep_is_stable(self):
        steps = [rom_step(f"rom@{us}us", BL1830_ROM) for us in obi.INTER_BYTE_SWEEP_US]
        self.assertTrue(obi.summarize_rom(steps).startswith("ROM stable"))

    def test_rom_disagreement_is_unstable(self):
        steps = [rom_step("rom@60us", BL1830_ROM), rom_step("rom@90us", BL1830_ROM),
                 rom_step("rom@120us", VALID_ROM)]
        summary = obi.summarize_rom(steps)
        self.assertTrue(summary.startswith("ROM unstable (2/3"))
        self.assertIn("rom@60us, rom@90us", summary)

    def test_all_blank_rom_reads(self):
        steps = [rom_step("rom@60us", b"\xFF" * 8)]
        self.assertIn("blank", obi.summarize_rom(steps))



# BL1815N #1 before and after the web UI "Clear errors" (dumps/ on 2026-10-01).
BL1815N_LOCKED_MSG = ("13 07 0F 64 32 03 88 F3 41 43 CB 95 1A 68 00 00 C1 C1 40 41 01 E0 02 03 "
                      "F0 D0 8E BE 5F 58 00 21 C1 02 0E 70 00 30 02 93")
BL1815N_UNLOCKED_MSG = ("13 07 0F 64 32 03 88 F3 41 43 CB 95 1A 68 00 00 74 74 40 41 01 E0 02 03 "
                        "F0 D0 8E BE A0 B3 00 21 C1 02 0E 70 00 30 02 93")


def dump(msg: str, label: str = "pack", timestamp: str = "2026-10-01T00:00:00",
         decoded: dict[str, str] | None = None) -> dict[str, object]:
    return {"label": label, "timestamp": timestamp, "steps": [
        {"name": "lxt_msg", "response": msg, "error": "", "decoded": decoded or {}}]}


class HistoryTests(unittest.TestCase):
    def test_rom_of_reads_rom_from_lxt_msg(self):
        self.assertEqual(obi.rom_of(dump(BL1815N_LOCKED_MSG)), "13 07 0F 64 32 03 88 F3")

    def test_rom_of_silent_pack_is_none(self):
        self.assertIsNone(obi.rom_of(dump(" ".join(["FF"] * 40))))

    def test_unlock_diff_shows_bytes_and_decoded_lock(self):
        changes = obi.diff_reports(dump(BL1815N_LOCKED_MSG), dump(BL1815N_UNLOCKED_MSG))
        self.assertEqual(changes, [
            "lxt_msg.lock_if_lxt: LOCKED -> UNLOCKED",
            "lxt_msg[16]: C1 -> 74",
            "lxt_msg[17]: C1 -> 74",
            "lxt_msg[28]: 5F -> A0",
            "lxt_msg[29]: 58 -> B3",
        ])

    def test_stale_decoded_keys_from_old_dumps_are_ignored(self):
        old = dump(BL1815N_LOCKED_MSG, decoded={"crc": "FAIL (calc 0x61, got 0x57)"})
        self.assertEqual(obi.diff_reports(old, dump(BL1815N_LOCKED_MSG)), [])

    def test_history_finds_same_pack_only_oldest_first(self):
        other_pack = BL1815N_LOCKED_MSG.replace("88 F3", "01 51", 1)
        with tempfile.TemporaryDirectory() as tmp:
            for name, report in {
                "late.json": dump(BL1815N_UNLOCKED_MSG, "late", "2026-10-01T22:00:00"),
                "early.json": dump(BL1815N_LOCKED_MSG, "early", "2026-10-01T21:00:00"),
                "other.json": dump(other_pack, "other"),
            }.items():
                Path(tmp, name).write_text(json.dumps(report), encoding="utf-8")

            previous = obi.find_previous_reads("13 07 0F 64 32 03 88 F3", Path(tmp))
            self.assertEqual([p.name for p, _ in previous], ["early.json", "late.json"])

            log: list[str] = []
            obi.report_history(dump(BL1815N_UNLOCKED_MSG), Path(tmp), log.append)
            self.assertIn("seen 2x before", log[0])
            self.assertIn("no changes since late.json", log[1])

    def test_history_first_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            log: list[str] = []
            obi.report_history(dump(BL1815N_LOCKED_MSG), Path(tmp), log.append)
            self.assertIn("first read", log[0])

    def test_compare_identical_dumps(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp, "a.json"), Path(tmp, "b.json")
            a.write_text(json.dumps(dump(BL1815N_LOCKED_MSG)), encoding="utf-8")
            b.write_text(json.dumps(dump(BL1815N_LOCKED_MSG)), encoding="utf-8")
            self.assertEqual(obi.compare(a, b), ["no differences"])


if __name__ == "__main__":
    unittest.main()
