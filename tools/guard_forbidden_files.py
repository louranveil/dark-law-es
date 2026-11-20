"""Rechaza commits que incluyan ROMs, savestates o saves de emulador.

El proyecto solo distribuye parches (BPS), nunca ROMs originales ni modificadas.
Este script se ejecuta desde el hook ``.githooks/pre-commit`` y puede usarse
también a mano: ``python tools/guard_forbidden_files.py``.

Un archivo en el índice se rechaza si:

* su extensión es de ROM, savestate o save de emulador, o
* su tamaño parece el de una ROM de SNES (múltiplo de 32 KiB, con o sin
  cabecera de copiador de 512 bytes, y de al menos 256 KiB), aunque se haya
  renombrado.

Los parches (.bps, .ips, .ups) están permitidos.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import PurePosixPath

FORBIDDEN_EXTENSIONS = frozenset(
    {
        # SNES / Super Famicom ROM images
        ".sfc", ".smc", ".swc", ".fig", ".gd3", ".ufo",
        # Other console ROM images. ".md" (Mega Drive) is left out on purpose: it is Markdown.
        ".nes", ".gb", ".gbc", ".gba", ".gen", ".smd", ".n64", ".z64", ".pce",
        # Generic ROM name, emulator savestates and battery saves
        ".rom", ".mss", ".srm",
    }
)

ROM_BLOCK_SIZE = 0x8000
COPIER_HEADER_SIZE = 0x200
MIN_ROM_SIZE = 0x40000


def has_forbidden_extension(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in FORBIDDEN_EXTENSIONS


def looks_like_rom_size(size: int) -> bool:
    """True for sizes a SNES ROM image can have, with or without copier header."""
    if size < MIN_ROM_SIZE:
        return False
    return size % ROM_BLOCK_SIZE == 0 or (size - COPIER_HEADER_SIZE) % ROM_BLOCK_SIZE == 0


def find_violations(entries: list[tuple[str, int]]) -> list[str]:
    """Return one message per offending ``(path, size)`` entry."""
    problems = []
    for path, size in entries:
        if has_forbidden_extension(path):
            problems.append(f"{path}: extension reserved for ROMs, savestates or saves")
        elif looks_like_rom_size(size):
            problems.append(f"{path}: size {size} bytes looks like a ROM image")
    return problems


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout


def staged_entries() -> list[tuple[str, int]]:
    names = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").split(b"\0")
    entries = []
    for raw in filter(None, names):
        path = raw.decode("utf-8", "surrogateescape")
        size = int(_git("cat-file", "-s", f":{path}").decode().strip())
        entries.append((path, size))
    return entries


def main() -> int:
    problems = find_violations(staged_entries())
    if not problems:
        return 0
    print("Commit rejected: ROMs, savestates and saves must never enter the repository.", file=sys.stderr)
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    print("Distribute patches (.bps) instead. Unstage the files with `git restore --staged <file>`.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
