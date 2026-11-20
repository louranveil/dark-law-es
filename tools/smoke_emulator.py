#!/usr/bin/env python3
"""Prueba de humo del emulador con la ROM real de Dark Law.

Comprueba, con la ROM y Mesen reales, que la cadena de depuración funciona de
extremo a extremo: arranque, captura, memoria de vídeo, determinismo entre
sesiones nuevas y reproducción de savestates. No fija ningún hash derivado de la
ROM: solo invariantes y coincidencias entre ejecuciones.

La ROM se recibe con --rom o con la variable DARK_LAW_ROM, y Mesen con
--mesen-bin o MESEN_BIN. Requiere el paquete mesen_probe instalado y
MESEN_FOR_AI_DIR apuntando a mesen-for-ai parcheado.

Límite: capture_colors_come_from_cgram compara la captura con la CGRAM volcada
después de dibujar, así que solo es fiable con paleta estable (la pantalla de
título lo es); durante un fundido o una animación de paleta puede fallar sin
que haya ningún error.

Códigos de salida: 0 todo correcto, 1 alguna comprobación falló, 2 uso o
configuración incorrectos.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import struct
import sys
import tempfile
import zlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

SCREEN_WIDTH = 256
SCREEN_HEIGHT = 224
HIROM_FIRST_BANK = 0xC0  # el código de Dark Law corre en los bancos C0-FF
COPIER_HEADER_REMAINDER = 512  # tamaño % 1024 == 512 indica cabecera de copiador

ToolCaller = Callable[..., dict]


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class Snapshot:
    """Estado observable del emulador en un instante."""

    png: bytes
    cgram: bytes
    vram_sha256: str
    wram_sha256: str
    master_clock: int
    bank: int
    pc: int

    def fingerprint(self) -> tuple:
        return (
            hashlib.sha256(self.png).hexdigest(),
            hashlib.sha256(self.cgram).hexdigest(),
            self.vram_sha256,
            self.wram_sha256,
            self.master_clock,
        )


def decode_png_pixels(data: bytes) -> tuple[int, int, list[tuple[int, int, int]]]:
    """Decodifica un PNG RGB de 8 bits sin entrelazado (solo biblioteca estándar)."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    position, width, height = 8, 0, 0
    compressed = bytearray()
    while position < len(data):
        length, kind = struct.unpack(">I4s", data[position : position + 8])
        body = data[position + 8 : position + 8 + length]
        position += 12 + length
        if kind == b"IHDR":
            width, height, depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if (depth, color_type, interlace) != (8, 2, 0):
                raise ValueError(f"unsupported PNG layout: depth={depth} color={color_type} interlace={interlace}")
        elif kind == b"IDAT":
            compressed += body
    raw = zlib.decompress(bytes(compressed))
    stride = width * 3
    if len(raw) != height * (stride + 1):
        raise ValueError("PNG data size does not match its dimensions")

    pixels: list[tuple[int, int, int]] = []
    previous = bytearray(stride)
    for y in range(height):
        filter_type = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1 : (y + 1) * (stride + 1)])
        for x in range(stride):
            left = line[x - 3] if x >= 3 else 0
            up = previous[x]
            upper_left = previous[x - 3] if x >= 3 else 0
            if filter_type == 1:
                line[x] = (line[x] + left) & 255
            elif filter_type == 2:
                line[x] = (line[x] + up) & 255
            elif filter_type == 3:
                line[x] = (line[x] + (left + up) // 2) & 255
            elif filter_type == 4:
                estimate = left + up - upper_left
                distances = (abs(estimate - left), abs(estimate - up), abs(estimate - upper_left))
                best = (left, up, upper_left)[distances.index(min(distances))]
                line[x] = (line[x] + best) & 255
            elif filter_type != 0:
                raise ValueError(f"invalid PNG filter type {filter_type}")
        pixels.extend((line[i], line[i + 1], line[i + 2]) for i in range(0, stride, 3))
        previous = line
    return width, height, pixels


def cgram_colors(cgram: bytes) -> set[tuple[int, int, int]]:
    """Colores RGB de 8 bits de un volcado de CGRAM (BGR555 little endian), como los pinta Mesen."""
    colors = set()
    for offset in range(0, len(cgram) - 1, 2):
        word = cgram[offset] | (cgram[offset + 1] << 8)
        channels = (word & 0x1F, (word >> 5) & 0x1F, (word >> 10) & 0x1F)
        colors.add(tuple((value << 3) | (value >> 2) for value in channels))
    return colors


def has_copier_header(size: int) -> bool:
    return size % 1024 == COPIER_HEADER_REMAINDER


@contextmanager
def emulator_session(rom: Path, mesen_bin: str) -> Iterator[tuple[ToolCaller, dict]]:
    """Abre una sesión nueva de Mesen y la cierra al salir. Entrega (llamar, info de la ROM)."""
    from mesen_probe.daemon import ProbeDaemon  # importación tardía: solo esta parte necesita el emulador

    daemon = ProbeDaemon()
    try:
        loaded = daemon.call_tool("session.load_rom", {"rom": str(rom), "mesen_bin": mesen_bin})
        handle = loaded["session"]

        def call(tool: str, **arguments) -> dict:
            return daemon.call_tool(tool, {"session": handle, **arguments})

        yield call, loaded.get("romInfo", {})
    finally:
        daemon.sessions.close_all()


def take_snapshot(call: ToolCaller, workdir: Path, name: str) -> Snapshot:
    png_path = workdir / f"{name}.png"
    call("video.export_frame", path=str(png_path), format="png")
    vram = call("memory.export", memoryType="snesVideoRam", path=str(workdir / f"{name}.vram"))
    cgram_path = workdir / f"{name}.cgram"
    call("memory.export", memoryType="snesCgRam", path=str(cgram_path))
    wram = call("memory.export", memoryType="snesWorkRam", path=str(workdir / f"{name}.wram"))
    registers = call("cpu.registers")
    return Snapshot(
        png=png_path.read_bytes(),
        cgram=cgram_path.read_bytes(),
        vram_sha256=vram["sha256"],
        wram_sha256=wram["sha256"],
        master_clock=call("run.status")["masterClock"],
        bank=registers["k"],
        pc=registers["pc"],
    )


def boot_snapshot(rom: Path, mesen_bin: str, workdir: Path, frames: int, name: str) -> tuple[Snapshot, dict]:
    """Arranca desde el reset, avanza ``frames`` fotogramas y captura el estado."""
    with emulator_session(rom, mesen_bin) as (call, rom_info):
        call("run.step_frames", frames=frames, reset=True)
        return take_snapshot(call, workdir, name), rom_info


def check_boot(rom: Path, snapshot: Snapshot, rom_info: dict) -> list[Check]:
    size = rom.stat().st_size
    return [
        Check(
            "rom_has_no_copier_header",
            not has_copier_header(size),
            f"size {size} bytes, SHA-1 reported by Mesen {rom_info.get('fileSha1Hash', 'unknown')}",
        ),
        Check(
            "boots_into_hirom_banks",
            snapshot.bank >= HIROM_FIRST_BANK,
            f"program counter ${snapshot.bank:02X}:{snapshot.pc:04X} after reset",
        ),
    ]


def check_capture(snapshot: Snapshot) -> list[Check]:
    width, height, pixels = decode_png_pixels(snapshot.png)
    used = set(pixels)
    palette = cgram_colors(snapshot.cgram)
    outside = used - palette
    return [
        Check("capture_is_256x224", (width, height) == (SCREEN_WIDTH, SCREEN_HEIGHT), f"PNG is {width}x{height}"),
        Check(
            "capture_colors_come_from_cgram",
            not outside,
            f"{len(used)} distinct colors, {len(outside)} outside the CGRAM palette",
        ),
        Check("screen_is_drawn", len(used) >= 3, f"{len(used)} distinct colors on screen"),
    ]


def check_fresh_sessions_agree(first: Snapshot, second: Snapshot) -> Check:
    same = first.fingerprint() == second.fingerprint()
    return Check(
        "fresh_sessions_agree",
        same,
        "capture, CGRAM, VRAM, WRAM, and master clock identical in two fresh sessions"
        if same
        else f"fresh sessions differ: {first.fingerprint()} != {second.fingerprint()}",
    )


def check_savestate_replay(rom: Path, mesen_bin: str, workdir: Path, frames: int, replay_frames: int) -> Check:
    """Guarda un savestate, avanza, lo carga y avanza otra vez: ambas ejecuciones deben coincidir."""
    state_path = workdir / "replay.mss"
    with emulator_session(rom, mesen_bin) as (call, _):
        call("run.step_frames", frames=frames, reset=True)
        call("state.save", path=str(state_path))
        call("run.step_frames", frames=replay_frames)
        original = take_snapshot(call, workdir, "original_run")
        call("state.load", path=str(state_path))
        call("run.step_frames", frames=replay_frames)
        replay = take_snapshot(call, workdir, "replayed_run")
    same = original.fingerprint() == replay.fingerprint()
    return Check(
        "savestate_replay_matches",
        same,
        f"{replay_frames} frames after state.load reproduce the original run exactly"
        if same
        else f"replay differs: {original.fingerprint()} != {replay.fingerprint()}",
    )


def run_smoke(rom: Path, mesen_bin: str, workdir: Path, frames: int = 600, replay_frames: int = 90) -> list[Check]:
    checks: list[Check] = []
    try:
        first, rom_info = boot_snapshot(rom, mesen_bin, workdir, frames, "boot_a")
        checks += check_boot(rom, first, rom_info)
        checks += check_capture(first)
        second, _ = boot_snapshot(rom, mesen_bin, workdir, frames, "boot_b")
        checks.append(check_fresh_sessions_agree(first, second))
        checks.append(check_savestate_replay(rom, mesen_bin, workdir, frames, replay_frames))
    except Exception as error:  # un fallo del emulador es un fallo de la prueba, no un error de uso
        checks.append(Check("emulator_session", False, f"{type(error).__name__}: {error}"))
    return checks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke test of the emulator tooling against the real Dark Law ROM.")
    parser.add_argument("--rom", type=Path, default=os.environ.get("DARK_LAW_ROM"), help="path to the ROM (or set DARK_LAW_ROM)")
    parser.add_argument("--mesen-bin", default=os.environ.get("MESEN_BIN"), help="path to Mesen (or set MESEN_BIN)")
    parser.add_argument("--frames", type=int, default=600, help="frames to run from reset before capturing (default 600)")
    parser.add_argument("--replay-frames", type=int, default=90, help="frames of the savestate replay (default 90)")
    parser.add_argument(
        "--workdir",
        type=Path,
        help="directory for captures, dumps and the temporary savestate (default: a temporary directory that is deleted)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.rom is None or not Path(args.rom).is_file():
        print("error: give the ROM with --rom or DARK_LAW_ROM (the file must exist)", file=sys.stderr)
        return 2
    if not args.mesen_bin or not Path(args.mesen_bin).is_file():
        print("error: give Mesen with --mesen-bin or MESEN_BIN (the file must exist)", file=sys.stderr)
        return 2
    if args.frames < 1 or args.replay_frames < 1:
        print("error: --frames and --replay-frames must be at least 1", file=sys.stderr)
        return 2
    try:
        import mesen_probe  # noqa: F401
    except ImportError as error:
        print(f"error: cannot import mesen_probe ({error}); install it and set MESEN_FOR_AI_DIR", file=sys.stderr)
        return 2
    except Exception as error:  # mesen_probe se niega a cargarse si mesen-for-ai falta o no está parcheado
        print(f"error: mesen_probe cannot start: {error}", file=sys.stderr)
        return 2

    def execute(workdir: Path) -> list[Check]:
        workdir.mkdir(parents=True, exist_ok=True)
        return run_smoke(Path(args.rom), args.mesen_bin, workdir, args.frames, args.replay_frames)

    if args.workdir:
        checks = execute(args.workdir)
    else:
        with tempfile.TemporaryDirectory(prefix="dark-law-smoke-") as temporary:
            checks = execute(Path(temporary))

    for check in checks:
        print(f"{'PASS' if check.passed else 'FAIL'}  {check.name}: {check.detail}")
    failed = [check for check in checks if not check.passed]
    print(f"{len(checks) - len(failed)}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
