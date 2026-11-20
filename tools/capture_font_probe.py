#!/usr/bin/env python3
"""Captura el mensaje del intro de una o varias ROM de prueba de fuente latina.

Para cada ROM construida con build_latin_probe.py abre una sesión nueva de Mesen,
recorre la ruta del intro (reset, 600 fotogramas hasta el título, Start, A) y guarda
una captura PNG a los fotogramas indicados. La ruta es la del spike de la fuente
(docs/re/latin-font-spike.md); las ROM se leen, nunca se escriben.

Mesen se recibe con --mesen-bin o MESEN_BIN, y mesen_probe necesita MESEN_FOR_AI_DIR.

Códigos de salida: 0 capturas escritas, 1 falló una sesión del emulador, 2 uso incorrecto.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from smoke_emulator import emulator_session

TITLE_FRAMES = 600  # el título está en pantalla al fotograma 600 tras el reset
BUTTON_HOLD_FRAMES = 5
START_TO_A_FRAMES = 60
DEFAULT_CAPTURE_FRAMES = (500,)  # fotogramas tras pulsar A en los que aparece el mensaje del intro


def capture_rom(rom: Path, mesen_bin: str, out_dir: Path, frames_after_a: tuple[int, ...]) -> list[Path]:
    written = []
    with emulator_session(rom, mesen_bin) as (call, _):
        call("run.step_frames", frames=TITLE_FRAMES, reset=True)
        call("input.set", buttons={"start": True})
        call("run.step_frames", frames=BUTTON_HOLD_FRAMES)
        call("input.set", buttons={"start": False})
        call("run.step_frames", frames=START_TO_A_FRAMES)
        call("input.set", buttons={"a": True})
        call("run.step_frames", frames=BUTTON_HOLD_FRAMES)
        call("input.set", buttons={"a": False})
        elapsed = 0
        for target in sorted(frames_after_a):
            call("run.step_frames", frames=target - elapsed)
            elapsed = target
            path = out_dir / f"{rom.stem}-f{target}.png"
            call("video.export_frame", path=str(path), format="png")
            written.append(path)
    return written


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("roms", nargs="+", type=Path, help="ROM de prueba")
    parser.add_argument("--mesen-bin", default=os.environ.get("MESEN_BIN"), help="ejecutable de Mesen (o MESEN_BIN)")
    parser.add_argument("--out-dir", type=Path, required=True, help="directorio de las capturas")
    parser.add_argument(
        "--frames",
        type=int,
        nargs="+",
        default=list(DEFAULT_CAPTURE_FRAMES),
        help="fotogramas tras pulsar A en los que capturar (por defecto 500)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.mesen_bin or not Path(args.mesen_bin).is_file():
        print("error: give Mesen with --mesen-bin or MESEN_BIN (the file must exist)", file=sys.stderr)
        return 2
    missing = [rom for rom in args.roms if not rom.is_file()]
    if missing or any(frame < 1 for frame in args.frames):
        print(f"error: missing ROMs {missing} or a frame count below 1", file=sys.stderr)
        return 2
    args.out_dir.mkdir(parents=True, exist_ok=True)
    try:
        for rom in args.roms:
            for path in capture_rom(rom, args.mesen_bin, args.out_dir, tuple(args.frames)):
                print(path)
    except Exception as error:  # un fallo del emulador no es un error de uso
        print(f"error: emulator session failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
