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

import tour_messages as tour  # noqa: E402


class FakeEmulator:
    """Un emulador de mentira: WRAM de 4 KiB que ``script`` modifica al llegar a cada fotograma."""

    def __init__(self, script: dict[int, dict[int, int]] | None = None):
        self.ram = bytearray(0x1000)
        self.script = script or {}
        self.frame = 0
        self.calls: list[tuple[str, dict]] = []
        self.buttons: dict[str, bool] = {}
        self.held_log: list[tuple[int, dict]] = []

    def __call__(self, tool: str, **arguments) -> dict:
        self.calls.append((tool, arguments))
        if tool == "run.step_frames":
            for _ in range(arguments["frames"]):
                self.frame += 1
                self.held_log.append((self.frame, dict(self.buttons)))
                for address, value in self.script.get(self.frame, {}).items():
                    self.ram[address] = value
            return {}
        if tool == "input.set":
            self.buttons.update(arguments["buttons"])
            return {}
        if tool == "cpu.read_memory":
            assert arguments["memoryType"] == "snesWorkRam"
            start = arguments["address"]
            return {"bytes": list(self.ram[start : start + arguments["length"]])}
        return {}


def pointer_bytes(address: int) -> dict[int, int]:
    """Valores de WRAM para un puntero de nivel 0 (profundidad 0): $0A8F-$0A91 y $1D-$1F."""
    low, middle, bank = address & 0xFF, address >> 8 & 0xFF, address >> 16
    return {0x0A8F: low, 0x0A90: middle, 0x0A91: bank, 0x1D: low, 0x1E: middle, 0x1F: bank}


def map_document(runs: list[dict] | None = None, skeleton: str = "<C1>{0}<C4><C1>{1}<CD 01><C7>") -> dict:
    runs = runs or [
        {"number": 0, "start": "E7:379C", "end": "E7:37AE", "marker": "E7379B.0", "letters": 8, "ruler": False, "original_bytes": 26, "original_rows": [13]},
        {"number": 1, "start": "E7:37AF", "end": "E7:37C0", "marker": "E7379B.1", "letters": 80, "ruler": True, "original_bytes": 20, "original_rows": [13, 10]},
    ]
    return {"format": 1, "entries": [{"id": "E7:379B", "slots": ["E7362B#3"], "skeleton": skeleton, "runs": runs}]}


class RouteTests(unittest.TestCase):
    def test_the_built_in_routes_are_valid(self):
        for name, route in tour.ROUTES.items():
            with self.subTest(route=name):
                self.assertEqual(tour.validate_route(route)["name"], name)

    def test_route_frames_counts_waits_and_presses(self):
        route = {"name": "x", "start": {"reset": 0}, "steps": [{"wait": 10}, {"press": ["a"], "hold": 4, "release": 6, "times": 3}]}
        self.assertEqual(tour.route_frames(route), 10 + 3 * 10)

    def test_bad_routes_are_rejected(self):
        bad = [
            {"name": "x", "steps": []},
            {"name": "x", "start": {"state": "a", "reset": 1}, "steps": []},
            {"name": "x", "start": {"reset": -1}, "steps": []},
            {"name": "x", "start": {"reset": 1}, "steps": [{"wait": 0}]},
            {"name": "x", "start": {"reset": 1}, "steps": [{"press": ["turbo"], "hold": 1}]},
            {"name": "x", "start": {"reset": 1}, "steps": [{"press": ["a"]}]},
            {"name": "x", "start": {"reset": 1}, "steps": [{"press": ["a"], "hold": 0}]},
            {"name": "x", "start": {"reset": 1}, "steps": [{"press": ["a"], "hold": 1, "speed": 2}]},
            {"name": "x", "start": {"reset": 1}, "steps": [{"jump": 1}]},
            {"name": "x", "start": {"reset": 1}, "steps": ["a"]},
            {"name": "x", "start": {"reset": 1}, "steps": [], "extra": 1},
        ]
        for route in bad:
            with self.subTest(route=route), self.assertRaises(tour.RouteError):
                tour.validate_route(route)

    def test_unknown_built_in_route_names_the_choices(self):
        with self.assertRaises(tour.RouteError) as raised:
            tour.load_route("nowhere", None)
        self.assertIn("field", str(raised.exception))


class DecodeTests(unittest.TestCase):
    def block(self, values: dict[int, int]) -> bytes:
        ram = bytearray(0x1000)
        for address, value in values.items():
            ram[address] = value
        return bytes(ram[tour.BLOCK_START : tour.BLOCK_START + tour.BLOCK_LENGTH])

    def test_fields_come_from_the_documented_addresses(self):
        values = {0x0A4C: 2, 0x0A45: 5, 0x0A47: 13, 0x0A49: 7, 0x0AC1: 0x03, 0x0AC2: 0x02, 0x0A8D: 1, 0x0AC4: 6, 0x0AC5: 9}
        values.update({0x0A92: 0x9B, 0x0A93: 0x37, 0x0A94: 0xE7})  # nivel 1: 3 bytes desde $0A8F + 3
        sample = tour.decode_sample(10, self.block(values), bytes([0x34, 0x12, 0xE7]))
        self.assertEqual(sample.window_type, 2)
        self.assertEqual(sample.slots, (5, 13, 7))
        self.assertEqual(sample.message_id, 0x203)
        self.assertEqual(sample.depth, 1)
        self.assertEqual(sample.top_pointer, 0xE7379B)
        self.assertEqual(sample.direct_pointer, 0xE71234)
        self.assertEqual(sample.state, (6, 9))

    def test_a_short_read_is_an_error(self):
        with self.assertRaises(ValueError):
            tour.decode_sample(0, bytes(10), bytes(3))
        with self.assertRaises(ValueError):
            tour.decode_sample(0, self.block({}), bytes(2))

    def test_a_stack_depth_outside_the_block_is_an_error(self):
        with self.assertRaises(ValueError):
            tour.decode_sample(0, self.block({0x0A8D: 200}), bytes(3))

    def test_row_round_trip(self):
        sample = tour.Sample(5, 2, (1, 2, 3), 515, 1, 0xE7379B, 0xE7379B, (2, 5))
        self.assertEqual(tour.Sample.from_row(sample.to_row()), sample)


class ExecuteRouteTests(unittest.TestCase):
    def test_presses_hold_then_release_and_sampling_follows_poll(self):
        emulator = FakeEmulator()
        route = {"name": "x", "start": {"reset": 0}, "steps": [{"press": ["down"], "hold": 3, "release": 2, "times": 2}, {"wait": 1}]}
        recorder = tour.execute_route(emulator, route, None, poll=1)
        self.assertEqual(emulator.frame, 11)
        held = [frame for frame, buttons in emulator.held_log if buttons.get("down")]
        self.assertEqual(held, [1, 2, 3, 6, 7, 8])
        self.assertEqual(recorder.frames, 11)

    def test_poll_groups_the_frames_and_covers_the_tail(self):
        emulator = FakeEmulator()
        route = {"name": "x", "start": {"reset": 5}, "steps": [{"wait": 7}]}
        tour.execute_route(emulator, route, None, poll=3)
        steps = [arguments["frames"] for tool, arguments in emulator.calls if tool == "run.step_frames"]
        self.assertEqual(steps, [5, 3, 3, 1])

    def test_recorder_keeps_only_changes(self):
        emulator = FakeEmulator({4: {0x0A4C: 2}, 6: {0x0A47: 9}})
        route = {"name": "x", "start": {"reset": 0}, "steps": [{"wait": 8}]}
        recorder = tour.execute_route(emulator, route, None)
        self.assertEqual([(s.frame, s.window_type, s.slots[1]) for s in recorder.samples], [(0, 0, 0), (4, 2, 0), (6, 2, 9)])

    def test_a_savestate_route_needs_the_directory_and_the_file(self):
        route = {"name": "x", "start": {"state": "missing.mss"}, "steps": []}
        with self.assertRaises(tour.RouteError):
            tour.execute_route(FakeEmulator(), route, None)
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(tour.RouteError):
            tour.execute_route(FakeEmulator(), route, Path(directory))

    def test_a_savestate_is_loaded_by_absolute_path(self):
        emulator = FakeEmulator()
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "a.mss").write_bytes(b"x")
            tour.execute_route(emulator, {"name": "x", "start": {"state": "a.mss"}, "steps": []}, Path(directory))
        load = [arguments for tool, arguments in emulator.calls if tool == "state.load"]
        self.assertEqual(len(load), 1)
        self.assertTrue(Path(load[0]["path"]).is_absolute())

    def test_the_tour_sees_a_message_draw_through_the_fake_ram(self):
        script = {
            2: {0x0A4C: 1, **pointer_bytes(0xE7379C)},  # el puntero entra en el tramo 0
            3: {0x0A4C: 2, 0x0A47: 13, **pointer_bytes(0xE737AE)},  # se dibuja: el puntero llega al fin
        }
        emulator = FakeEmulator(script)
        recorder = tour.execute_route(emulator, {"name": "x", "start": {"reset": 0}, "steps": [{"wait": 5}]})
        visits = tour.track_visits(recorder.samples, tour.RunIndex(map_document()))
        self.assertEqual(len(visits), 1)
        self.assertEqual((visits[0].drawn_frame, visits[0].window_type, tour.slots_drawn(visits[0])), (3, 2, 13))


def sample(frame, pointer, window_type=1, slots=(0, 0, 0), message_id=0, depth=0):
    return tour.Sample(frame, window_type, slots, message_id, depth, pointer, pointer, (0, 0))


class TrackTests(unittest.TestCase):
    def setUp(self):
        self.index = tour.RunIndex(map_document())

    def test_a_visit_is_drawn_when_the_pointer_reaches_the_end(self):
        visits = tour.track_visits(
            [sample(1, 0xE7379C, 1, (20, 20, 0)), sample(3, 0xE737AE, 2, (0, 13, 0), 3), sample(9, 0xE737AE, 2, (0, 13, 0), 3)], self.index
        )
        (visit,) = visits
        self.assertEqual((visit.first_frame, visit.last_frame, visit.drawn_frame), (1, 9, 3))
        self.assertEqual((visit.window_type, visit.message_id, visit.slots_at_end), (2, 3, (0, 13, 0)))
        self.assertEqual(visit.types_seen, {1, 2})

    def test_the_stale_counters_before_the_draw_are_not_the_measure(self):
        visits = tour.track_visits([sample(1, 0xE7379C, 2, (0, 31, 0))], self.index)
        self.assertIsNone(visits[0].drawn_frame)
        self.assertIsNone(visits[0].slots_at_end)
        self.assertIsNone(tour.slots_drawn(visits[0]))

    def test_leaving_and_coming_back_makes_a_new_visit(self):
        visits = tour.track_visits(
            [sample(1, 0xE737AE, 2, (0, 4, 0)), sample(2, 0xE70000), sample(3, 0xE737AE, 2, (0, 5, 0))], self.index
        )
        self.assertEqual([visit.drawn_frame for visit in visits], [1, 3])

    def test_moving_to_the_next_run_closes_the_visit(self):
        visits = tour.track_visits([sample(1, 0xE737AE, 2, (0, 4, 0)), sample(2, 0xE737AF, 2, (0, 4, 0))], self.index)
        self.assertEqual([visit.run.number for visit in visits], [0, 1])

    def test_the_counter_depends_on_the_window_type(self):
        for window_type, expected in ((1, 7), (2, 9), (3, None), (0, None)):
            with self.subTest(window_type=window_type):
                (visit,) = tour.track_visits([sample(1, 0xE737AE, window_type, (7, 9, 11))], self.index)
                self.assertEqual(tour.slots_drawn(visit), expected)

    def test_the_map_rejects_a_boundary_shared_by_two_runs(self):
        runs = map_document()["entries"][0]["runs"]
        runs[1]["start"] = runs[0]["end"]
        with self.assertRaises(ValueError):
            tour.RunIndex(map_document(runs))

    def test_the_map_format_is_checked(self):
        with self.assertRaises(ValueError):
            tour.RunIndex({"format": 2, "entries": []})


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.index = tour.RunIndex(map_document())

    def test_summary_separates_rulers_lists_unreached_and_flags_mixed_types(self):
        visits = tour.track_visits(
            [sample(1, 0xE737AE, 2, (0, 13, 0), 3), sample(5, 0xE70000), sample(9, 0xE737C0, 2, (0, 32, 0), 3)], self.index
        )
        summary = tour.summarize(visits, self.index)
        self.assertEqual(summary["runs drawn"], 2)
        stats = summary["by window type"]["2"]
        self.assertEqual(stats["max_slots"], 32)
        self.assertEqual(stats["ruler"], [{"id": "E7:379B", "run": 1, "slots": 32, "letters": 80}])
        self.assertEqual(summary["unreached runs"], [])
        self.assertEqual(summary["entries with several window types"], [])

    def test_unreached_runs_name_their_entry_and_slots(self):
        visits = tour.track_visits([sample(1, 0xE737AE, 2, (0, 13, 0), 3)], self.index)
        summary = tour.summarize(visits, self.index)
        self.assertEqual(summary["unreached runs"], [{"id": "E7:379B", "run": 1, "slots": ["E7362B#3"]}])

    def test_an_entry_drawn_in_two_window_types_is_flagged(self):
        visits = tour.track_visits(
            [sample(1, 0xE737AE, 2, (0, 13, 0), 3), sample(2, 0), sample(3, 0xE737C0, 1, (24, 0, 0), 3)], self.index
        )
        self.assertEqual(tour.summarize(visits, self.index)["entries with several window types"], ["E7:379B"])

    def test_a_run_counts_once_however_many_visits_it_had(self):
        visits = tour.track_visits(
            [sample(1, 0xE737AE, 2, (0, 13, 0)), sample(2, 0), sample(3, 0xE737AE, 2, (0, 13, 0))], self.index
        )
        self.assertEqual(tour.summarize(visits, self.index)["runs drawn"], 1)

    def test_report_text_mentions_unreached_runs(self):
        text = tour.format_report([], self.index)
        self.assertIn("unreached runs: 2", text)
        self.assertIn("E7:379B run 0 (E7362B#3)", text)


class WalkRouteTests(unittest.TestCase):
    def test_the_walk_is_valid_and_deterministic(self):
        first = tour.walk_route(7, 20)
        self.assertEqual(first, tour.walk_route(7, 20))
        self.assertNotEqual(first, tour.walk_route(8, 20))
        tour.validate_route(first)
        moves = [step for step in first["steps"] if step["press"] != ["a"]]
        self.assertEqual(len(moves), 20)
        self.assertEqual(len(first["steps"]) - len(moves), 5)  # una pulsación de A cada 4 pasos
        self.assertEqual(first["start"], {"state": "field-start.mss"})

    def test_a_walk_without_interaction_has_only_moves(self):
        route = tour.walk_route(1, 10, interact_every=0)
        self.assertTrue(all(step["press"][0] in ("up", "down", "left", "right") for step in route["steps"]))

    def test_the_walk_command_prints_a_route(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(tour.main(["walk", "--seed", "3", "--moves", "4"]), 0)
        tour.validate_route(json.loads(output.getvalue()))


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.index = tour.RunIndex(map_document())

    def test_a_saturated_ruler_measures_the_limit_of_its_window_type(self):
        visits = tour.track_visits([sample(1, 0xE737C0, 2, (0, 32, 0), 3)], self.index)  # regla de 40 celdas, se dibujan 32
        limits = tour.measured_slot_limits(visits)
        self.assertEqual(limits[2], {"slots": 32, "evidence": "ruler"})
        self.assertEqual(limits[1], {"slots": 24, "evidence": "code"})

    def test_a_ruler_that_just_fits_measures_nothing(self):
        runs = map_document()["entries"][0]["runs"]
        runs[1]["letters"] = 64
        index = tour.RunIndex(map_document(runs))
        visits = tour.track_visits([sample(1, 0xE737C0, 2, (0, 32, 0), 3)], index)
        self.assertEqual(tour.measured_slot_limits(visits)[2]["evidence"], "code")

    def test_rulers_that_disagree_are_an_error(self):
        runs = map_document()["entries"][0]["runs"]
        runs.append({"number": 2, "start": "E7:37C2", "end": "E7:37C9", "marker": "x", "letters": 80, "ruler": True, "original_bytes": 8, "original_rows": [3]})
        index = tour.RunIndex(map_document(runs))
        visits = tour.track_visits([sample(1, 0xE737C0, 2, (0, 32, 0)), sample(2, 0), sample(3, 0xE737C9, 2, (0, 30, 0))], index)
        with self.assertRaises(ValueError):
            tour.measured_slot_limits(visits)

    def test_budgets_give_letters_per_run_with_their_evidence(self):
        visits = tour.track_visits(
            [sample(1, 0xE737AE, 2, (0, 13, 0), 3), sample(2, 0), sample(3, 0xE737C0, 2, (0, 32, 0), 3)], self.index
        )
        result = tour.budgets(visits, self.index)
        self.assertEqual(result["slot limits"]["2"], {"slots": 32, "evidence": "ruler"})
        runs = result["entries"]["E7:379B"]["runs"]
        self.assertEqual(runs["0"]["max"], 64)
        self.assertEqual(runs["0"]["evidence"], "measured")
        self.assertEqual(runs["0"]["window_type"], [2])

    def test_a_window_type_without_a_limit_gives_no_budget(self):
        visits = tour.track_visits([sample(1, 0xE737AE, 3, (0, 13, 0), 3)], self.index)
        run = tour.budgets(visits, self.index)["entries"]["E7:379B"]["runs"]["0"]
        self.assertIsNone(run["max"])

    def test_a_run_seen_in_two_types_takes_the_smaller_budget(self):
        visits = tour.track_visits(
            [sample(1, 0xE737AE, 2, (0, 13, 0)), sample(2, 0), sample(3, 0xE737AE, 1, (13, 0, 0))], self.index
        )
        run = tour.budgets(visits, self.index)["entries"]["E7:379B"]["runs"]["0"]
        self.assertEqual((run["window_type"], run["max"], run["evidence"]), ([1, 2], 48, "code"))

    def test_the_budgets_command_writes_json(self):
        recorder = tour.Recorder()
        recorder.add(sample(3, 0xE737AE, 2, (0, 13, 0), 3))
        with tempfile.TemporaryDirectory() as directory:
            log, map_path, out = (Path(directory) / name for name in ("log.json", "map.json", "out.json"))
            rom = Path(directory) / "rom.sfc"
            rom.write_bytes(b"x")
            tour.write_log(log, recorder, {"name": "x"}, rom)
            map_path.write_text(json.dumps(map_document()), encoding="utf-8")
            self.assertEqual(tour.main(["budgets", "--map", str(map_path), "--log", str(log), "--out", str(out)]), 0)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["entries"]["E7:379B"]["runs"]["0"]["max"], 64)


class BufferCheckerTests(unittest.TestCase):
    LETTERS = "AB.0"

    def setUp(self):
        import script_format as sf

        self.font = bytes((7 * index + position) % 251 for index in range(4) for position in range(32))
        rom = bytearray(0x120000)
        self.addresses = [0x400 + 0x20 * slot for slot in range(32)]
        for kind, table in tour.BUFFER_TABLES.items():
            for slot, address in enumerate(self.addresses):
                offset = sf.cpu_to_offset(table) + 2 * slot
                rom[offset : offset + 2] = address.to_bytes(2, "little")
        self.rom = bytes(rom)
        runs = map_document()["entries"][0]["runs"]
        runs[0]["marker"] = "AB.0"
        self.index = tour.RunIndex(map_document(runs))

    def letter(self, char):
        position = self.LETTERS.index(char)
        return self.font[32 * position : 32 * position + 32]

    def draw(self, emulator, text, break_slot=None, first=0):
        for slot in range(first, first + len(text) // 2):
            left, right = self.letter(text[2 * (slot - first)]), self.letter(text[2 * (slot - first) + 1])
            top, bottom = left[:16] + right[:16], left[16:] + right[16:]
            if slot == break_slot:
                top = bytes(32)
            emulator.ram[self.addresses[slot] : self.addresses[slot] + 32] = top
            emulator.ram[self.addresses[slot] + 0x100 : self.addresses[slot] + 0x120] = bottom

    def check(self, text, break_slot=None, window_type=2):
        emulator = FakeEmulator()
        self.draw(emulator, text, break_slot)
        checker = tour.BufferChecker(emulator, self.index, self.rom, self.LETTERS, self.font)
        checker(sample(1, 0xE737AE, window_type, (0, 2, 0)))
        return checker.results

    def test_a_marker_drawn_as_written_matches(self):
        (result,) = self.check("AB.0").values()
        self.assertEqual((result["bad_slots"], result["window_type"]), ([], 2))

    def test_a_marker_that_follows_other_text_on_the_page_is_read_where_it_was_drawn(self):
        emulator = FakeEmulator()
        self.draw(emulator, "AB.0", first=3)
        checker = tour.BufferChecker(emulator, self.index, self.rom, self.LETTERS, self.font)
        checker(sample(1, 0xE737AE, 2, (0, 5, 0)))  # el contador acaba en 5: el marcador de 2 celdas ocupa la 3 y la 4
        (result,) = checker.results.values()
        self.assertEqual(result["bad_slots"], [])

    def test_a_counter_smaller_than_the_marker_is_a_mismatch(self):
        emulator = FakeEmulator()
        checker = tour.BufferChecker(emulator, self.index, self.rom, self.LETTERS, self.font)
        checker(sample(1, 0xE737AE, 2, (0, 1, 0)))
        (result,) = checker.results.values()
        self.assertEqual(result["bad_slots"], [0, 1])

    def test_a_wrong_slot_is_reported(self):
        (result,) = self.check("AB.0", break_slot=1).values()
        self.assertEqual(result["bad_slots"], [1])

    def test_only_the_end_of_a_marker_run_in_a_known_window_is_checked(self):
        self.assertEqual(self.check("AB.0", window_type=3), {})
        emulator = FakeEmulator()
        checker = tour.BufferChecker(emulator, self.index, self.rom, self.LETTERS, self.font)
        checker(sample(1, 0xE737AF, 2))  # el inicio de otro tramo
        checker(sample(2, 0))
        self.assertEqual(checker.results, {})

    def test_a_run_is_checked_once(self):
        emulator = FakeEmulator()
        self.draw(emulator, "AB.0")
        checker = tour.BufferChecker(emulator, self.index, self.rom, self.LETTERS, self.font)
        checker(sample(1, 0xE737AE, 2))
        reads = len(emulator.calls)
        checker(sample(2, 0xE737AE, 2))
        self.assertEqual(len(emulator.calls), reads)

    def test_the_route_hook_receives_every_recorded_sample(self):
        seen = []
        tour.execute_route(FakeEmulator({2: {0x0A4C: 2}}), {"name": "x", "start": {"reset": 0}, "steps": [{"wait": 3}]}, on_sample=seen.append)
        self.assertEqual([item.frame for item in seen], [0, 1, 2, 3])


class OpenerTests(unittest.TestCase):
    def test_the_opener_of_each_run_is_the_last_c0_or_c1_before_it(self):
        skeleton = "<C8 40><C0><E7 14 01>{0}<C4><C0>{1}<C4><C1>{2}<C5><C8 20>{3}<FF>"
        self.assertEqual(tour.run_openers(skeleton), {0: "C0", 1: "C0", 2: "C1", 3: "C1"})

    def test_a_run_with_no_opener_has_none(self):
        self.assertEqual(tour.run_openers("<C8 40>{0}<FF>"), {0: None})

    def test_the_index_carries_the_opener(self):
        index = tour.RunIndex(map_document())
        self.assertEqual({info.opener for info in index.runs.values()}, {"C1"})

    def test_the_summary_counts_observed_types_by_opener(self):
        index = tour.RunIndex(map_document())
        visits = tour.track_visits([sample(1, 0xE737AE, 2, (0, 13, 0)), sample(2, 0), sample(3, 0xE737C0, 1, (24, 0, 0))], index)
        self.assertEqual(tour.summarize(visits, index)["drawn runs by opening command and window type"], {"C1": {"2": 1, "1": 1}})

    def test_budgets_predict_the_runs_that_were_not_reached_from_their_opener(self):
        index = tour.RunIndex(map_document(skeleton="<C0>{0}<C4><C1>{1}<C7>"))
        visits = tour.track_visits([sample(1, 0xE737AE, 1, (24, 0, 0), 3)], index)
        runs = tour.budgets(visits, index)["entries"]["E7:379B"]["runs"]
        self.assertEqual((runs["0"]["max"], runs["0"]["evidence"]), (48, "code"))
        self.assertEqual((runs["1"]["window_type"], runs["1"]["max"]), ([2], 64))
        self.assertIn("predicted", runs["1"]["evidence"])


class OriginalRomModelTests(unittest.TestCase):
    def test_predicted_slots_follow_the_row_start_of_each_window_type(self):
        self.assertEqual(tour.predicted_slots([13], 2), 13)
        self.assertEqual(tour.predicted_slots([13, 10], 2), 26)
        self.assertEqual(tour.predicted_slots([11, 12], 1), 24)
        self.assertEqual(tour.predicted_slots([0, 12], 1), 24)
        self.assertIsNone(tour.predicted_slots([4], 3))

    def test_a_run_of_the_original_rom_is_checked_and_a_difference_is_reported(self):
        runs = [
            {"number": 0, "start": "E7:379C", "end": "E7:37AE", "marker": None, "letters": None, "ruler": False, "original_bytes": 26, "original_rows": [13]},
            {"number": 1, "start": "E7:37AF", "end": "E7:37C0", "marker": None, "letters": None, "ruler": False, "original_bytes": 20, "original_rows": [13, 10]},
        ]
        index = tour.RunIndex(map_document(runs))
        visits = tour.track_visits([sample(1, 0xE737AE, 2, (0, 13, 0)), sample(2, 0), sample(3, 0xE737C0, 2, (0, 25, 0))], index)
        checked = tour.summarize(visits, index)["original text checked against the row model"]
        self.assertEqual(checked["checked"], 2)
        self.assertEqual(checked["differ"], [{"id": "E7:379B", "run": 1, "measured": 25, "predicted": 26}])
        self.assertIn("1 agree", tour.format_report(visits, index))

    def test_marker_runs_are_not_compared_with_the_japanese_model(self):
        index = tour.RunIndex(map_document())
        visits = tour.track_visits([sample(1, 0xE737AE, 2, (0, 4, 0))], index)
        self.assertEqual(tour.summarize(visits, index)["original text checked against the row model"]["checked"], 0)


class LogAndCliTests(unittest.TestCase):
    def test_log_round_trip_and_report_command(self):
        recorder = tour.Recorder()
        for frame, pointer, slots in ((0, 0xE70000, 0), (3, 0xE737AE, 13)):
            recorder.add(sample(frame, pointer, 2, (0, slots, 0), 3))
        with tempfile.TemporaryDirectory() as directory:
            rom = Path(directory) / "marker.sfc"
            rom.write_bytes(b"rom")
            log = Path(directory) / "log.json"
            tour.write_log(log, recorder, {"name": "x"}, rom)
            document, samples = tour.read_log(log)
            self.assertEqual(samples, recorder.samples)
            self.assertEqual(document["rom"], "marker.sfc")
            map_path = Path(directory) / "map.json"
            map_path.write_text(json.dumps(map_document()), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = tour.main(["report", "--map", str(map_path), "--log", str(log), "--json"])
            self.assertEqual(code, 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["summary"]["runs drawn"], 1)
            self.assertEqual(result["visits"][0]["slots"], [0, 13, 0])

    def test_run_command_refuses_a_missing_rom_or_emulator(self):
        with tempfile.TemporaryDirectory() as directory:
            map_path = Path(directory) / "map.json"
            map_path.write_text(json.dumps(map_document()), encoding="utf-8")
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                code = tour.main(["run", "--rom", str(Path(directory) / "none.sfc"), "--map", str(map_path), "--mesen-bin", "none.exe"])
            self.assertEqual(code, 2)

    def test_poll_must_be_positive(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(tour.main(["run", "--rom", "a", "--map", "b", "--poll", "0"]), 2)


if __name__ == "__main__":
    unittest.main()
