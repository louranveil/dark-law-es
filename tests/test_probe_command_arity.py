from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import probe_command_arity as probe  # noqa: E402

FETCH = probe.COMMAND_FETCH_PC


class InterpretReadsTests(unittest.TestCase):
    def test_one_argument(self):
        # C8: comando en 0, argumento leído en 1 por otra rutina, siguiente comando en 2
        self.assertEqual(probe.interpret_reads([(0, FETCH), (1, "3B9C"), (2, FETCH), (2, "4573")]), 1)

    def test_no_arguments(self):
        self.assertEqual(probe.interpret_reads([(0, FETCH), (1, FETCH), (1, "4573")]), 0)

    def test_skipped_bytes_count_as_arguments(self):
        # DC: solo se leen dos argumentos, pero el siguiente comando está en la posición 5
        self.assertEqual(probe.interpret_reads([(0, FETCH), (1, "3B7B"), (2, "3B7B"), (5, FETCH)]), 4)

    def test_blocked_engine_has_no_answer(self):
        self.assertIsNone(probe.interpret_reads([(0, FETCH), (1, "3B9C")]))
        self.assertIsNone(probe.interpret_reads([]))

    def test_the_command_itself_is_not_a_next_command(self):
        self.assertIsNone(probe.interpret_reads([(0, FETCH)]))


class SubcommandTests(unittest.TestCase):
    def test_patterns_start_with_the_subcommand(self):
        patterns = probe.subcommand_patterns(0x3B)
        self.assertEqual(patterns["ascending"][0], 0x3B)
        self.assertEqual(patterns["zeros"], (0x3B, 0, 0, 0, 0, 0))

    def test_first_args_can_be_a_list(self):
        self.assertEqual(probe.parse_first_args("00,0A,FF", b"", 0xFE), [0, 10, 255])
        self.assertEqual(probe.parse_first_args("", b"", 0xFE), [])

    def test_bad_first_args_are_an_error(self):
        with self.assertRaises(ValueError):
            probe.parse_first_args("zz", b"", 0xFE)

    def test_main_requires_a_command_with_first_args(self):
        import io
        from contextlib import redirect_stderr

        err = io.StringIO()
        with redirect_stderr(err):
            code = probe.main(["--rom", "x", "--mesen-bin", "y", "--state", "z", "--first-args", "00"])
        self.assertEqual(code, 2)
        self.assertIn("--command", err.getvalue())


if __name__ == "__main__":
    unittest.main()
