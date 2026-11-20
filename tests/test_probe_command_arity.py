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


if __name__ == "__main__":
    unittest.main()
