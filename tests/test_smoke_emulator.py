from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import os
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import smoke_emulator as smoke  # noqa: E402

RED_WORD, GREEN_WORD, BLUE_WORD = 0x001F, 0x03E0, 0x7C00
RED, GREEN, BLUE = (255, 0, 0), (0, 255, 0), (0, 0, 255)


def words_to_bytes(words: list[int]) -> bytes:
    return b"".join(word.to_bytes(2, "little") for word in words)


def filtered_png(width: int, height: int, pixels: list[tuple[int, int, int]]) -> bytes:
    """Codifica un PNG RGB aplicando los cinco filtros por turnos (referencia independiente del decodificador)."""
    stride = width * 3
    flat = bytes(channel for pixel in pixels for channel in pixel)
    rows = [flat[y * stride : (y + 1) * stride] for y in range(height)]
    raw = bytearray()
    previous = bytes(stride)
    for y, row in enumerate(rows):
        filter_type = y % 5
        out = bytearray()
        for x in range(stride):
            left = row[x - 3] if x >= 3 else 0
            up = previous[x]
            upper_left = previous[x - 3] if x >= 3 else 0
            if filter_type == 0:
                predicted = 0
            elif filter_type == 1:
                predicted = left
            elif filter_type == 2:
                predicted = up
            elif filter_type == 3:
                predicted = (left + up) // 2
            else:
                estimate = left + up - upper_left
                distances = (abs(estimate - left), abs(estimate - up), abs(estimate - upper_left))
                predicted = (left, up, upper_left)[distances.index(min(distances))]
            out.append((row[x] - predicted) & 255)
        raw += bytes([filter_type]) + out
        previous = row

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw)))
        + chunk(b"IEND", b"")
    )


def snapshot(png: bytes = b"", cgram: bytes = b"", *, vram: str = "v", wram: str = "w", clock: int = 1, bank: int = 0xC0) -> smoke.Snapshot:
    return smoke.Snapshot(png=png, cgram=cgram, vram_sha256=vram, wram_sha256=wram, master_clock=clock, bank=bank, pc=0x1234)


def screen_png(colors: list[tuple[int, int, int]], width: int = 256, height: int = 224) -> bytes:
    return filtered_png(width, height, [colors[(x + y) % len(colors)] for y in range(height) for x in range(width)])


class PngDecoderTests(unittest.TestCase):
    def test_round_trips_all_five_filters(self) -> None:
        pixels = [((x * 37 + y * 11) & 255, (x * 5 + y * 71) & 255, (x * 13 + y * 3) & 255) for y in range(7) for x in range(9)]

        width, height, decoded = smoke.decode_png_pixels(filtered_png(9, 7, pixels))

        self.assertEqual((width, height), (9, 7))
        self.assertEqual(decoded, pixels)

    def test_rejects_data_that_is_not_a_png(self) -> None:
        with self.assertRaisesRegex(ValueError, "not a PNG"):
            smoke.decode_png_pixels(b"P6\n1 1\n255\n\x00\x00\x00")

    def test_rejects_unsupported_layouts(self) -> None:
        png = bytearray(filtered_png(1, 1, [RED]))
        png[25] = 6  # tipo de color RGBA
        with self.assertRaisesRegex(ValueError, "unsupported PNG layout"):
            smoke.decode_png_pixels(bytes(png))


class PaletteTests(unittest.TestCase):
    def test_cgram_words_become_mesens_rgb_colors(self) -> None:
        colors = smoke.cgram_colors(words_to_bytes([RED_WORD, GREEN_WORD, BLUE_WORD, 0x7FFF, 0x0000]))

        self.assertEqual(colors, {RED, GREEN, BLUE, (255, 255, 255), (0, 0, 0)})

    def test_copier_header_is_detected_by_size(self) -> None:
        self.assertTrue(smoke.has_copier_header(4 * 1024 * 1024 + 512))
        self.assertFalse(smoke.has_copier_header(4 * 1024 * 1024))


class CaptureCheckTests(unittest.TestCase):
    PALETTE = words_to_bytes([RED_WORD, GREEN_WORD, BLUE_WORD])

    def results(self, shot: smoke.Snapshot) -> dict[str, bool]:
        return {check.name: check.passed for check in smoke.check_capture(shot)}

    def test_a_valid_capture_passes_every_check(self) -> None:
        shot = snapshot(screen_png([RED, GREEN, BLUE]), self.PALETTE)

        self.assertEqual(self.results(shot), {"capture_is_256x224": True, "capture_colors_come_from_cgram": True, "screen_is_drawn": True})

    def test_wrong_size_fails(self) -> None:
        shot = snapshot(screen_png([RED, GREEN, BLUE], width=256, height=239), self.PALETTE)

        self.assertFalse(self.results(shot)["capture_is_256x224"])

    def test_a_color_missing_from_cgram_fails(self) -> None:
        shot = snapshot(screen_png([RED, GREEN, (1, 2, 3)]), self.PALETTE)

        self.assertFalse(self.results(shot)["capture_colors_come_from_cgram"])

    def test_a_blank_screen_is_not_drawn(self) -> None:
        shot = snapshot(screen_png([RED]), self.PALETTE)

        self.assertFalse(self.results(shot)["screen_is_drawn"])


class BootCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def rom(self, size: int) -> Path:
        path = self.directory / "game.bin"
        path.write_bytes(bytes(size))
        return path

    def results(self, size: int, bank: int) -> dict[str, bool]:
        checks = smoke.check_boot(self.rom(size), snapshot(bank=bank), {"fileSha1Hash": "ABC"})
        return {check.name: check.passed for check in checks}

    def test_headerless_rom_running_in_hirom_banks_passes(self) -> None:
        self.assertEqual(self.results(1024, 0xC0), {"rom_has_no_copier_header": True, "boots_into_hirom_banks": True})

    def test_copier_header_fails(self) -> None:
        self.assertFalse(self.results(1024 + 512, 0xC0)["rom_has_no_copier_header"])

    def test_running_outside_the_hirom_banks_fails(self) -> None:
        self.assertFalse(self.results(1024, 0x00)["boots_into_hirom_banks"])

    def test_the_report_carries_the_sha1_reported_by_mesen(self) -> None:
        checks = smoke.check_boot(self.rom(1024), snapshot(), {"fileSha1Hash": "ABC123"})

        self.assertIn("ABC123", checks[0].detail)


class IdentityCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.rom = Path(directory.name) / "game.sfc"
        self.rom.write_bytes(b"known content")
        self.sha1 = hashlib.sha1(b"known content").hexdigest().upper()

    def check(self, *, mesen: str | None = None, sha1: str | None = None, size: int = 13) -> smoke.Check:
        info = {"fileSha1Hash": self.sha1 if mesen is None else mesen}
        return smoke.check_identity(self.rom, info, expected_sha1=sha1 or self.sha1, expected_size=size)

    def test_the_expected_file_seen_identically_by_mesen_passes(self) -> None:
        result = self.check()

        self.assertTrue(result.passed, result.detail)
        self.assertIn(self.sha1, result.detail)

    def test_comparison_ignores_the_case_of_the_hashes(self) -> None:
        self.assertTrue(self.check(mesen=self.sha1.lower(), sha1=self.sha1.lower()).passed)

    def test_a_different_file_fails_and_reports_both_hashes(self) -> None:
        result = self.check(sha1="0" * 40)

        self.assertFalse(result.passed)
        self.assertIn(self.sha1, result.detail)
        self.assertIn("0" * 40, result.detail)

    def test_a_wrong_size_fails(self) -> None:
        self.assertFalse(self.check(size=14).passed)

    def test_mesen_reporting_another_hash_fails(self) -> None:
        result = self.check(mesen="F" * 40)

        self.assertFalse(result.passed)
        self.assertIn("Mesen reports", result.detail)

    def test_mesen_reporting_nothing_fails(self) -> None:
        self.assertFalse(self.check(mesen="").passed)


class PinnedIdentityTests(unittest.TestCase):
    def test_the_constants_match_the_identity_document(self) -> None:
        document = (REPO / "docs" / "re" / "rom-identity.md").read_text(encoding="utf-8")

        self.assertIn(smoke.EXPECTED_ROM_SHA1, document)
        self.assertIn(str(smoke.EXPECTED_ROM_SIZE), document)


class AgreementCheckTests(unittest.TestCase):
    def test_identical_snapshots_agree(self) -> None:
        self.assertTrue(smoke.check_fresh_sessions_agree(snapshot(png=b"x"), snapshot(png=b"x")).passed)

    def test_each_observable_difference_is_detected(self) -> None:
        base = snapshot(png=b"x", cgram=b"c")
        different = (
            snapshot(png=b"y", cgram=b"c"),
            snapshot(png=b"x", cgram=b"d"),
            snapshot(png=b"x", cgram=b"c", vram="other"),
            snapshot(png=b"x", cgram=b"c", wram="other"),
            snapshot(png=b"x", cgram=b"c", clock=2),
        )
        for other in different:
            self.assertFalse(smoke.check_fresh_sessions_agree(base, other).passed)


class CommandLineTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.rom = self.directory / "game.sfc"
        self.rom.write_bytes(bytes(8))
        self.mesen = self.directory / "Mesen.exe"
        self.mesen.write_bytes(b"")

    def run_main(self, *args: str) -> tuple[int, str]:
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            return smoke.main(list(args)), err.getvalue()

    def test_missing_rom_is_a_usage_error(self) -> None:
        code, err = self.run_main("--rom", str(self.directory / "none.sfc"), "--mesen-bin", str(self.mesen))

        self.assertEqual(code, 2)
        self.assertIn("--rom or DARK_LAW_ROM", err)

    def test_missing_emulator_is_a_usage_error(self) -> None:
        code, err = self.run_main("--rom", str(self.rom), "--mesen-bin", str(self.directory / "none.exe"))

        self.assertEqual(code, 2)
        self.assertIn("--mesen-bin or MESEN_BIN", err)

    def test_non_positive_frame_counts_are_a_usage_error(self) -> None:
        code, err = self.run_main("--rom", str(self.rom), "--mesen-bin", str(self.mesen), "--frames", "0")

        self.assertEqual(code, 2)
        self.assertIn("at least 1", err)


def real_run_unavailable() -> str | None:
    rom, mesen = os.environ.get("DARK_LAW_ROM"), os.environ.get("MESEN_BIN")
    if not rom or not Path(rom).is_file():
        return "set DARK_LAW_ROM to the ROM path to run the real-ROM smoke test"
    if not mesen or not Path(mesen).is_file():
        return "set MESEN_BIN to the Mesen executable to run the real-ROM smoke test"
    if not os.environ.get("MESEN_FOR_AI_DIR") or importlib.util.find_spec("mesen_probe") is None:
        return "install mesen_probe and set MESEN_FOR_AI_DIR to run the real-ROM smoke test"
    return None


@unittest.skipIf(real_run_unavailable() is not None, real_run_unavailable() or "")
class RealRomTests(unittest.TestCase):
    def test_every_smoke_check_passes_on_the_real_rom(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checks = smoke.run_smoke(Path(os.environ["DARK_LAW_ROM"]), os.environ["MESEN_BIN"], Path(directory))

        report = "\n".join(f"{'PASS' if c.passed else 'FAIL'} {c.name}: {c.detail}" for c in checks)
        self.assertTrue(checks and all(check.passed for check in checks), report)
        self.assertEqual(len(checks), 8, report)
        self.assertEqual(checks[0].name, "rom_is_the_verified_dump", report)


if __name__ == "__main__":
    unittest.main()
