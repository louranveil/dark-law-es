from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import force_messages as force  # noqa: E402
import tour_messages as tour  # noqa: E402


class ForcedEmulator:
    """WRAM de 4 KiB con un motor de mentira: al estar en modo de ejecución, ``script`` dice qué cambia en cada fotograma."""

    def __init__(self, script: dict[int, dict[int, int]] | None = None, depth: int = 0, finish_at: int | None = None):
        self.ram = bytearray(0x1000)
        self.ram[tour.STACK_DEPTH] = depth
        self.script = script or {}
        self.finish_at = finish_at
        self.frame = 0
        self.calls: list[tuple[str, dict]] = []
        self.buttons: dict[str, bool] = {}
        self.pressed_frames: list[int] = []

    def __call__(self, tool: str, **arguments) -> dict:
        self.calls.append((tool, arguments))
        if tool == "state.load":
            self.frame = 0
            self.ram[force.RUN_MODE] = 1  # el estado guardado espera un evento
            self.ram[force.FIELD_MODE] = 1
            self.ram[tour.WINDOW_TYPE] = 1  # una ventana que quedó abierta
            return {}
        if tool == "run.step_frames":
            for _ in range(arguments["frames"]):
                self.frame += 1
                if self.buttons.get("a"):
                    self.pressed_frames.append(self.frame)
                for address, value in self.script.get(self.frame, {}).items():
                    self.ram[address] = value
                if self.finish_at is not None and self.frame >= self.finish_at:
                    self.ram[force.RUN_MODE] = 1
            return {}
        if tool == "input.set":
            self.buttons.update(arguments["buttons"])
            return {}
        if tool == "cpu.write_memory":
            start = arguments["address"]
            self.ram[start : start + len(arguments["bytes"])] = bytes(arguments["bytes"])
            return {}
        if tool == "cpu.read_memory":
            start = arguments["address"]
            return {"bytes": list(self.ram[start : start + arguments["length"]])}
        return {}


def document(entries: list[tuple[str, str, list[str]]]) -> dict:
    """Un mapa mínimo: (id, dirección actual, slots)."""
    return {
        "format": 1,
        "entries": [
            {"id": entry_id, "address": address, "slots": slots, "skeleton": "<C1>{0}<C7>", "runs": []}
            for entry_id, address, slots in entries
        ],
    }


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.document = document(
            [
                ("E7:379B", "E7:FC81", ["E7362B#3"]),
                ("E7:372B", "E7:372B", ["E7362B#0"]),
                ("E2:EE93", "E2:EE93", ["E2EE73#0", "E2EE73#9"]),
                ("EC:0100", "EC:0100", ["EC0027#7"]),
            ]
        )

    def test_entries_are_ordered_by_current_address_and_carry_the_table_index(self):
        planned = force.plan_entries(self.document)
        self.assertEqual([item.entry_id for item in planned], ["E2:EE93", "E7:372B", "E7:379B", "EC:0100"])
        self.assertEqual([item.message_id for item in planned], [0, 0, 3, 7])
        self.assertEqual(planned[2].address, 0xE7FC81)

    def test_a_table_filter_accepts_the_address_with_or_without_the_colon(self):
        for text in ("E7362B", "e7:362b"):
            planned = force.plan_entries(self.document, tables=[text])
            self.assertEqual({item.entry_id for item in planned}, {"E7:372B", "E7:379B"})

    def test_an_id_filter_and_a_skip_set(self):
        self.assertEqual([item.entry_id for item in force.plan_entries(self.document, ids=["E7:379b"])], ["E7:379B"])
        skipped = force.plan_entries(self.document, skip={"E7:372B"})
        self.assertNotIn("E7:372B", [item.entry_id for item in skipped])

    def test_shards_partition_the_selection(self):
        parts = [force.plan_entries(self.document, shard=(index, 3)) for index in range(3)]
        flat = sorted(item.entry_id for part in parts for item in part)
        self.assertEqual(flat, sorted(entry["id"] for entry in self.document["entries"]))
        self.assertEqual(len({item.entry_id for part in parts for item in part}), 4)

    def test_bad_shards_and_maps_are_rejected(self):
        for text in ("4/4", "-1/2", "x", "1/0", "1"):
            with self.assertRaises(force.PlanError, msg=text):
                force.parse_shard(text)
        with self.assertRaises(force.PlanError):
            force.plan_entries({"format": 2, "entries": []})

    def test_the_message_id_is_the_index_of_the_first_pointer(self):
        self.assertEqual(force.entry_message_id(["E2EE73#12", "E2EE73#3"]), 12)
        self.assertIsNone(force.entry_message_id([]))


class ForceScriptTests(unittest.TestCase):
    def test_the_pointer_goes_to_the_current_stack_level_and_the_engine_is_put_in_run_mode(self):
        emulator = ForcedEmulator(depth=2)
        emulator.ram[force.STATE_FIRST : force.STATE_FIRST + force.STATE_LENGTH] = b"\x09" * force.STATE_LENGTH
        force.force_script(emulator, 0xE7FC81, 3)
        level = tour.STACK_BASE + 3 * 2
        self.assertEqual(list(emulator.ram[level : level + 3]), [0x81, 0xFC, 0xE7])
        self.assertEqual(emulator.ram[tour.STACK_DEPTH], 2)
        self.assertEqual(emulator.ram[force.RUN_MODE], force.RUNNING)
        self.assertEqual(emulator.ram[force.FIELD_MODE], force.RUNNING)
        self.assertEqual(emulator.ram[tour.WINDOW_TYPE], 0)
        self.assertEqual(list(emulator.ram[force.STATE_FIRST : force.STATE_FIRST + force.STATE_LENGTH]), [0] * force.STATE_LENGTH)
        self.assertEqual(emulator.ram[tour.MESSAGE_ID] | emulator.ram[tour.MESSAGE_ID + 1] << 8, 3)

    def test_without_a_message_id_the_id_bytes_are_left_alone(self):
        emulator = ForcedEmulator()
        emulator.ram[tour.MESSAGE_ID] = 0x55
        force.force_script(emulator, 0xE7372B)
        self.assertEqual(emulator.ram[tour.MESSAGE_ID], 0x55)


class DriveEntryTests(unittest.TestCase):
    ENTRY = force.ForcedEntry("E7:372B", 0xE7372B, 0)

    def test_the_entry_finishes_when_the_dispatcher_returns_to_mode_one(self):
        script = {3: {tour.WINDOW_TYPE: 2, 0x0A47: 13, 0x0A8F: 0x3E, 0x0A90: 0x37, 0x0A91: 0xE7}}
        emulator = ForcedEmulator(script, finish_at=7)
        result = force.drive_entry(emulator, self.ENTRY, Path("state.mss"), frame_offset=100)
        self.assertEqual((result.outcome, result.frames), ("finished", 7))
        self.assertEqual(result.types_seen, [2])  # el tipo 1 que dejó el estado guardado se borra al forzar y el 0 no cuenta
        self.assertEqual(emulator.calls[0], ("state.load", {"path": "state.mss"}))
        self.assertEqual(result.samples[0].frame, 101)
        self.assertEqual(result.to_json()["outcome"], "finished")

    def test_an_engine_that_never_finishes_times_out(self):
        result = force.drive_entry(ForcedEmulator(), self.ENTRY, Path("s"), max_frames=15)
        self.assertEqual((result.outcome, result.frames), ("timeout", 15))

    def test_a_is_pulsed_and_released(self):
        emulator = ForcedEmulator()
        force.drive_entry(emulator, self.ENTRY, Path("s"), max_frames=45)
        self.assertEqual(emulator.pressed_frames[:force.PRESS_HOLD], list(range(1, force.PRESS_HOLD + 1)))
        self.assertIn(force.PRESS_PERIOD + 1, emulator.pressed_frames)
        self.assertNotIn(force.PRESS_HOLD + 1, emulator.pressed_frames)
        self.assertFalse(emulator.buttons["a"])

    def test_poll_groups_the_frames(self):
        emulator = ForcedEmulator(finish_at=6)
        result = force.drive_entry(emulator, self.ENTRY, Path("s"), poll=2)
        self.assertEqual(result.frames, 6)
        steps = [arguments["frames"] for tool, arguments in emulator.calls if tool == "run.step_frames"]
        self.assertEqual(steps, [2, 2, 2])

    def test_the_hook_sees_each_sample(self):
        seen: list[tour.Sample] = []
        force.drive_entry(ForcedEmulator(finish_at=3), self.ENTRY, Path("s"), on_sample=seen.append)
        self.assertEqual([sample.frame for sample in seen], [1, 2, 3])


class SummaryTests(unittest.TestCase):
    def setUp(self):
        runs = [
            {"number": 0, "start": "E7:379C", "end": "E7:37AE", "marker": "E7379B.0", "letters": 8, "ruler": False, "original_bytes": 26, "original_rows": [13]},
            {"number": 1, "start": "E7:37AF", "end": "E7:37C0", "marker": "E7379B.1", "letters": 8, "ruler": False, "original_bytes": 20, "original_rows": [13]},
        ]
        self.document = {
            "format": 1,
            "entries": [
                {"id": "E7:379B", "address": "E7:379B", "slots": ["E7362B#3"], "skeleton": "<C1>{0}<C4><C1>{1}<C7>", "runs": runs},
                {"id": "E7:3800", "address": "E7:3800", "slots": ["E7362B#4"], "skeleton": "<C2 01 00 02 00>", "runs": []},
            ],
        }
        self.index = tour.RunIndex(self.document)

    def test_entries_runs_and_window_types_are_counted_by_table(self):
        samples = [
            tour.decode_sample(1, self.block(2, 0xE737AE, (0, 4, 0)), bytes(3)),
            tour.decode_sample(2, self.block(2, 0, (0, 4, 0)), bytes(3)),
        ]
        visits = tour.track_visits(samples, self.index)
        log = {"forced": [
            {"id": "E7:379B", "outcome": "finished", "types_seen": [2]},
            {"id": "E7:3800", "outcome": "timeout", "types_seen": [3]},
        ]}
        summary = force.summarize_forced([log, log], self.index, visits)
        self.assertEqual(summary["entries forced"], 2)
        self.assertEqual(summary["by table"], {"E7362B": {"entries": 2, "finished": 1, "timeout": 1, "error": 0}})
        self.assertEqual(summary["runs drawn by table and window type"], {"E7362B": {"2": 1}})
        self.assertEqual(summary["runs of forced entries not drawn"], [{"id": "E7:379B", "run": 1}])
        self.assertEqual(summary["entries opening a window type other than 1 or 2"], {"3": ["E7:3800"]})
        self.assertEqual(summary["entries that did not finish"], ["E7:3800"])

    @staticmethod
    def block(window_type: int, pointer: int, slots: tuple[int, int, int]) -> bytes:
        block = bytearray(tour.BLOCK_LENGTH)
        block[tour.WINDOW_TYPE - tour.BLOCK_START] = window_type
        for address, value in zip(tour.SLOT_COUNTERS, slots):
            block[address - tour.BLOCK_START] = value
        level = tour.STACK_BASE - tour.BLOCK_START
        block[level : level + 3] = pointer.to_bytes(3, "little")
        return bytes(block)


class LogAndCliTests(unittest.TestCase):
    def test_extra_keys_survive_a_log_round_trip_and_do_not_break_reading(self):
        recorder = tour.Recorder()
        recorder.add(tour.decode_sample(1, bytes(tour.BLOCK_LENGTH), bytes(3)))
        with tempfile.TemporaryDirectory() as directory:
            rom = Path(directory) / "r.sfc"
            rom.write_bytes(b"x")
            path = Path(directory) / "log.json"
            tour.write_log(path, recorder, {"name": "forced"}, rom, None, {"forced": [{"id": "E7:372B"}]})
            written = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(written["forced"], [{"id": "E7:372B"}])
            document_, samples = force.read_forced(path)
            self.assertEqual(len(samples), 1)
            self.assertEqual(document_["forced"], [{"id": "E7:372B"}])

    def test_plan_command_lists_entries_without_the_emulator(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "map.json"
            path.write_text(json.dumps(document([("E7:372B", "E7:372B", ["E7362B#0"]), ("E2:EE93", "E2:EE93", ["E2EE73#0"])])), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                status = force.main(["plan", "--map", str(path), "--table", "E7362B"])
            self.assertEqual(status, 0)
            self.assertIn("E7:372B id 0", out.getvalue())
            self.assertNotIn("E2:EE93", out.getvalue())

    def test_run_command_needs_an_existing_savestate_and_emulator(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "map.json"
            path.write_text(json.dumps(document([("E7:372B", "E7:372B", ["E7362B#0"])])), encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                status = force.main(["run", "--map", str(path), "--rom", str(path), "--savestates", directory, "--mesen-bin", "none"])
            self.assertEqual(status, 2)
            self.assertIn("savestate not found", err.getvalue())

    def test_options_must_be_positive(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            status = force.main(["run", "--map", "m", "--rom", "r", "--poll", "0"])
        self.assertEqual(status, 2)


if __name__ == "__main__":
    unittest.main()
