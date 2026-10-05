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

    def test_session_encodes_transactions_and_splits_replies(self):
        fake = FakeFirmwareSerial({obi.CMD_SESSION: bytes([1, 0x06, 0xFF, 0xAA, 0xBB])})
        replies = obi.ObiLink(fake, timeout_s=0.1).session([
            obi.Transaction(bytes([0xCC, 0xD9]), 1),
            obi.Transaction(bytes([0x33]), 2, reset=False, delay_ms=30),
        ])
        self.assertEqual(fake.sent[0], bytes([1, 11, 5, 0xD1,
                                              0x01, 0, 2, 1, 0xCC, 0xD9,
                                              0x00, 30, 1, 2, 0x33]))
        self.assertEqual([(r.presence, r.read) for r in replies],
                         [(1, b"\x06"), (None, b"\xAA\xBB")])

    def test_session_rejects_oversized_transaction(self):
        link = obi.ObiLink(FakeFirmwareSerial({}), timeout_s=0.1)
        with self.assertRaisesRegex(obi.ObiError, "at most 255"):
            link.session([obi.Transaction(b"\xCC", 256)])

    def test_session_on_old_firmware_explains_how_to_fix(self):
        fake = FakeFirmwareSerial({obi.CMD_SESSION: b""})
        with self.assertRaisesRegex(obi.ObiError, "flash the firmware"):
            obi.ObiLink(fake, timeout_s=0.1).session([obi.Transaction(b"\xCC", 0)])

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

    def test_f0513_temperature_in_tenths_of_kelvin(self):
        # Raw 3022 from the BL1830; read as 1/100 C it was 30.22, the same ~30 C every pack showed.
        self.assertEqual(obi.decode_known("f0513_temp", bytes.fromhex("CE0B")),
                         {"temp_c": "29.05", "temp_raw": "3022"})

    def test_all_ff_is_flagged_as_no_answer(self):
        self.assertIn("no answer", obi.decode_known("lxt_data", b"\xFF" * 29)["hint"])

    def test_lxt_data_offsets_match_web_ui(self):
        # Web UI reads pack at response[2], cell1 at [4], temp at [16]; payload drops 2 bytes.
        payload = bytearray(29)
        payload[0:2] = (18000).to_bytes(2, "little")
        payload[2:4] = (3600).to_bytes(2, "little")
        payload[14:16] = (2982).to_bytes(2, "little")
        decoded = obi.decode_known("lxt_data", bytes(payload))
        self.assertEqual(decoded["pack_v"], "18.000")
        self.assertTrue(decoded["cells_v"].startswith("[3.6,"))
        self.assertEqual(decoded["temp1_c"], "25.05")

    def test_lxt_data_soc_and_real_capacity(self):
        # BL1840B #1 right after a full charge (dumps/ on 2026-10-05).
        decoded = obi.decode_known("lxt_data", BL1840B_CHARGED_DATA)
        self.assertEqual(decoded["soc_pct"], "88.9")
        self.assertEqual(decoded["real_capacity_mah"], "3080")
        self.assertEqual(decoded["temp_raw"], "2987 2994")
        self.assertNotIn("target_capacity_mah", decoded)

    def test_extended_lxt_data_decodes_error_block(self):
        payload = bytearray(0x70)
        payload[0x1D:0x1F] = (4000).to_bytes(2, "little")
        payload[0x30] = 0x12
        payload[0x57:0x5D] = bytes([1, 2, 3, 4, 5, 6])
        decoded = obi.decode_known("lxt_data_ext", bytes(payload))
        self.assertEqual(decoded["target_capacity_mah"], "4000")
        self.assertEqual(decoded["error_status"], "0x12")
        self.assertEqual(decoded["error_counters"], "01 02 03 04 05 06")


def msg_of(payload_hex: str) -> bytes:
    return bytes.fromhex(payload_hex)[obi.MSG_OFFSET:]


def with_nybble(payload_hex: str, nybble: int, value: int) -> bytes:
    payload = bytearray(bytes.fromhex(payload_hex))
    index = obi.MSG_OFFSET + nybble // 2
    if nybble % 2:
        payload[index] = (payload[index] & 0x0F) | (value << 4)
    else:
        payload[index] = (payload[index] & 0xF0) | value
    return bytes(payload)


class MessageLayoutTests(unittest.TestCase):
    """Checksums and fields from other projects, checked against our real dumps."""

    def test_unlocked_packs_have_every_checksum_right(self):
        for payload in (BL1840B_CHARGED_MSG, BL1815N_UNLOCKED_MSG):
            decoded = obi.decode_known("lxt_msg", bytes.fromhex(payload))
            self.assertEqual((decoded["checksums"], decoded["lock_cause"]), ("all ok", "none"))

    def test_bms_lock_is_failure_code_f_and_inverted_primary_checksums(self):
        decoded = obi.decode_known("lxt_msg", bytes.fromhex(BL1815N_LOCKED_MSG))
        self.assertEqual(decoded["failure_code"], "15")
        self.assertEqual(decoded["checksums"],
                         "CS0 5, calc A (inverted); CS1 8, calc 7 (inverted); CS2 5, calc A (inverted)")
        self.assertEqual(decoded["lock_cause"],
                         "failure code 15; CS0-CS2 inverted (BMS lock; Clear errors undid it on BL1815N #1)")

    def test_charger_lock_nybble_is_reported_with_its_broken_checksum(self):
        decoded = obi.decode_known("lxt_msg", with_nybble(BL1840B_CHARGED_MSG, 34, 4))
        self.assertIn("nybble 34 = 4", decoded["lock_cause"])
        self.assertIn("CS2", decoded["lock_cause"])
        self.assertEqual(decoded["lock_if_lxt"], "UNLOCKED")

    def test_damage_rating_went_up_after_full_cycle(self):
        before = obi.decode_known("lxt_msg", bytes.fromhex(BL1840B_FIRST_MSG))
        after = obi.decode_known("lxt_msg", bytes.fromhex(BL1840B_CHARGED_MSG))
        self.assertEqual((before["damage_rating"], after["damage_rating"]), ("0", "1"))

    def test_counters(self):
        decoded = obi.decode_known("lxt_msg", bytes.fromhex(BL1840B_CHARGED_MSG))
        self.assertEqual((decoded["charge_count_if_lxt"], decoded["second_counter"]), ("16", "12"))

    def test_charge_count_uses_13th_bit(self):
        payload = with_nybble(BL1840B_CHARGED_MSG, obi.NYBBLE_CHARGE_COUNT, 1)
        self.assertEqual(obi.decode_known("lxt_msg", payload)["charge_count_if_lxt"], "4112")

    def test_capacity_formats(self):
        self.assertEqual(obi.decode_capacity(0x82), "4.0Ah")
        # Whole-Ah format reported by PocketOBI: 0x05 swaps to 0x50 = 80 > 60.
        self.assertEqual(obi.decode_capacity(0x05), "5.0Ah")

    def test_checksum_ranges(self):
        msg = msg_of(BL1840B_CHARGED_MSG)
        self.assertEqual([obi.checksum_calc(msg, c) for c in obi.MSG_CHECKSUMS], [6, 5, 0xA, 3, 3])


class MemoryReadTests(unittest.TestCase):
    def test_ack_is_checked(self):
        self.assertEqual(obi.decode_known("d4_od_events", bytes([3, 0x06])),
                         {"ack": "06 ok", "count": "3"})
        self.assertEqual(obi.decode_known("d4_od_events", bytes([3, 0x00]))["ack"], "00 (no ACK)")

    def test_overload_counters(self):
        # first = b0>>6 | b1<<2, second = b3 | (b4&3)<<8, third = b5>>4 | (b6&0x3F)<<4
        payload = bytes([0x40, 0x01, 0x00, 0x05, 0x01, 0x20, 0x01, 0x06])
        self.assertEqual(obi.decode_known("d4_overload", payload)["counters"], "5 261 18")

    def test_wrong_length_is_flagged_instead_of_crashing(self):
        # compare/redecode feed whatever a dump holds; this used to raise IndexError.
        self.assertEqual(obi.decode_known("d4_assembly_date", b"\x01\x06"),
                         {"hint": "2 bytes; expected 4"})
        self.assertIn("hint", obi.decode_known("lxt_data_ext", bytes(range(1, 11))))

    def test_testmode_prefix_decodes_like_plain_read(self):
        payload = bytes([0x12, 0x04, 0x13, 0x06])
        self.assertEqual(obi.decode_known("tm_d4_assembly_date", payload)["date"], "19/04/2018")


class ProbeTests(unittest.TestCase):
    def test_no_presence_is_summarized(self):
        fake = FakeFirmwareSerial({obi.CMD_VERSION: bytes(3), obi.CMD_DEBUG_RAW: bytes([1, 0])})
        report = obi.probe(obi.ObiLink(fake, timeout_s=0.1), lambda _: None)
        self.assertIn("no presence", report["summary"][0])

    def test_testmode_runs_reads_between_entry_and_exit_in_one_session(self):
        reads = [r for r in obi.MEMORY_READS if r.name not in obi.TESTMODE_SKIP]
        reply = bytes([1, 0x06])
        for read in reads:
            reply += bytes([1]) + bytes(read.rsp_len - 1) + bytes([0x06])
        reply += bytes([1, 0x06])
        fake = FakeFirmwareSerial({obi.CMD_VERSION: bytes(3), obi.CMD_DEBUG_RAW: bytes([1, 0]),
                                   obi.CMD_SESSION: reply})
        report = obi.probe(obi.ObiLink(fake, timeout_s=0.1), lambda _: None, testmode=True)
        sessions = [frame for frame in fake.sent if frame[3] == obi.CMD_SESSION]
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0][8:12], obi.TESTMODE_ENTER)
        self.assertTrue(sessions[0].endswith(obi.TESTMODE_EXIT))
        names = [s["name"] for s in report["steps"] if s["name"].startswith("tm_")]
        self.assertEqual(names, ["tm_enter"] + [f"tm_{r.name}" for r in reads] + ["tm_exit"])
        od = next(s for s in report["steps"] if s["name"] == "tm_d4_od_events")
        self.assertEqual(od["decoded"]["ack"], "06 ok")

    def test_silent_testmode_is_not_summarized_as_real_data(self):
        reads = [r for r in obi.MEMORY_READS if r.name not in obi.TESTMODE_SKIP]
        rsp_len = sum(1 + r.rsp_len for r in reads) + 4
        fake = FakeFirmwareSerial({obi.CMD_VERSION: bytes(3), obi.CMD_DEBUG_RAW: bytes([1, 1]),
                                   obi.CMD_SESSION: b"\xFF" * rsp_len})
        report = obi.probe(obi.ObiLink(fake, timeout_s=0.1), lambda _: None, testmode=True)
        self.assertNotIn("tm_", " ".join(report["summary"]))

    def test_probe_without_testmode_sends_no_session(self):
        fake = FakeFirmwareSerial({obi.CMD_VERSION: bytes(3), obi.CMD_DEBUG_RAW: bytes([1, 0])})
        obi.probe(obi.ObiLink(fake, timeout_s=0.1), lambda _: None)
        self.assertFalse([frame for frame in fake.sent if frame[3] == obi.CMD_SESSION])

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
# BL1840B #1: first read (2026-10-02) and after a full discharge + charge (2026-10-05).
BL1840B_FIRST_MSG = ("12 04 13 64 05 05 01 C3 F1 26 BD 13 14 58 00 00 C1 C1 40 21 D0 80 02 0B "
                     "82 D0 8E 67 60 A3 00 01 02 02 0E E0 00 A0 04 E1")
BL1840B_CHARGED_MSG = ("12 04 13 64 05 05 01 C3 F1 26 BD 13 14 58 00 00 24 24 40 21 D0 80 02 0B "
                       "82 D0 8E 67 60 A5 00 03 02 02 0E 01 00 C0 04 33")
BL1840B_CHARGED_DATA = bytes.fromhex(
    "D44FFC0FF90FF30FF20FF30F2E05AB0BB20B008040E558080C80527800")


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
            "lxt_msg.checksums: CS0 5, calc A (inverted); CS1 8, calc 7 (inverted); "
            "CS2 5, calc A (inverted) -> all ok",
            "lxt_msg.failure_code: 15 -> 0",
            "lxt_msg.lock_cause: failure code 15; CS0-CS2 inverted "
            "(BMS lock; Clear errors undid it on BL1815N #1) -> none",
            "lxt_msg.lock_if_lxt: LOCKED -> UNLOCKED",
            "lxt_msg[16]: C1 -> 74  (rewritten on charge/unlock)",
            "lxt_msg[17]: C1 -> 74  (rewritten on charge/unlock)",
            "lxt_msg[28]: 5F -> A0  (failure code + CS0)",
            "lxt_msg[29]: 58 -> B3  (CS1 + CS2)",
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
