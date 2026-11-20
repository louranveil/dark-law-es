from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import guard_forbidden_files as guard  # noqa: E402

GUARD_SCRIPT = REPO / "tools" / "guard_forbidden_files.py"


class ExtensionTests(unittest.TestCase):
    def test_rom_savestate_and_save_extensions_are_forbidden_in_any_case(self) -> None:
        for name in ("a.sfc", "dir/b.SMC", "c.swc", "d.fig", "e.mss", "f.srm", "g.ROM", "h.gba"):
            self.assertTrue(guard.has_forbidden_extension(name), name)

    def test_patches_and_sources_are_allowed(self) -> None:
        for name in ("dark-law-es.bps", "fix.ips", "tools/guard.py", "docs/re/header.md", "text/dialogs.json"):
            self.assertFalse(guard.has_forbidden_extension(name), name)


class RomSizeTests(unittest.TestCase):
    def test_snes_rom_sizes_are_detected_with_and_without_copier_header(self) -> None:
        for size in (0x40000, 0x100000, 0x400000, 0x400000 + 0x200):
            self.assertTrue(guard.looks_like_rom_size(size), hex(size))

    def test_small_or_odd_sizes_are_not_roms(self) -> None:
        for size in (0, 1000, 0x8000, 0x3FFFF, 0x40001, 0x100000 + 7):
            self.assertFalse(guard.looks_like_rom_size(size), hex(size))


class FindViolationsTests(unittest.TestCase):
    def test_reports_each_offender_with_its_reason(self) -> None:
        problems = guard.find_violations(
            [("game.sfc", 10), ("renamed.dat", 0x400000), ("ok.bps", 5000), ("notes.md", 0x400000 + 1)]
        )

        self.assertEqual(len(problems), 2)
        self.assertIn("game.sfc", problems[0])
        self.assertIn("renamed.dat", problems[1])

    def test_clean_entries_have_no_violations(self) -> None:
        self.assertEqual(guard.find_violations([("a.py", 100), ("b.bps", 4096)]), [])


class HookIntegrationTests(unittest.TestCase):
    """Runs the script against a real temporary git repository."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        self.git("init", "-q")

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True, check=True)

    def run_guard(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(GUARD_SCRIPT)], cwd=self.repo, capture_output=True, text=True)

    def test_clean_commit_passes(self) -> None:
        (self.repo / "readme.md").write_text("hello")
        self.git("add", "readme.md")

        self.assertEqual(self.run_guard().returncode, 0)

    def test_staged_rom_by_extension_is_rejected(self) -> None:
        (self.repo / "game.sfc").write_bytes(b"x")
        self.git("add", "game.sfc")

        result = self.run_guard()

        self.assertEqual(result.returncode, 1)
        self.assertIn("game.sfc", result.stderr)

    def test_staged_renamed_rom_is_rejected_by_size(self) -> None:
        (self.repo / "data.bin").write_bytes(bytes(0x40000))
        self.git("add", "data.bin")

        result = self.run_guard()

        self.assertEqual(result.returncode, 1)
        self.assertIn("looks like a ROM image", result.stderr)

    def test_unstaged_rom_does_not_block_a_clean_commit(self) -> None:
        (self.repo / "game.sfc").write_bytes(b"x")
        (self.repo / "readme.md").write_text("hello")
        self.git("add", "readme.md")

        self.assertEqual(self.run_guard().returncode, 0)


if __name__ == "__main__":
    unittest.main()
