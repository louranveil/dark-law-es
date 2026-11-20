#!/usr/bin/env python3
"""Mide cuántos argumentos consume cada comando del motor de texto con ejecución forzada.

Para cada código C0-FF (salvo los prefijos de glifo FA-FD) se carga un savestate en el que
el motor está parado entre comandos, se escribe en WRAM el guion ``cmd, 01 02 03 04 05 06,
C7 C7 C7 C7``, se apunta el nivel actual de la pila de punteros de script a ese guion y se
deja correr el motor. Un watch de lectura sobre el guion registra qué rutina lee cada byte:
el motor busca cada comando en ``$D1:3B13``, así que la posición de la siguiente captura de
comando menos uno es el número de argumentos. Si el motor se bloquea esperando algo, no hay
siguiente captura y el resultado es "bloquea" (no se puede medir así).

Hace falta un savestate del juego en el intro con la ROM verificada (por ejemplo, tomado en
el texto "300年前" justo antes de la segunda línea) y que la pila de punteros ya tenga un
nivel de script activo. Se pasa con --state; los savestates no se guardan en el repositorio.

Variables y rutinas (ver docs/re/text-engine.md): pila de punteros de script en WRAM
``$0A8D`` (profundidad) y ``$0A8F`` (3 bytes por nivel), puntero activo en ``$1D``-``$1F``,
estado del autómata de comandos en ``$0AC4``-``$0AC5``.

Códigos de salida: 0 medición terminada, 2 uso o configuración incorrectos.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from smoke_emulator import emulator_session

SCRIPT_OFFSET = 0xF000  # zona de WRAM libre en el estado del intro donde se escribe el guion de prueba
WRAM_BANK = 0x7E0000
POINTER_STACK_DEPTH, POINTER_STACK_BASE = 0x0A8D, 0x0A8F
ACTIVE_POINTER = 0x1D
COMMAND_STATE = 0x0AC4
COMMAND_FETCH_PC = "3B13"  # $D1:3B13, LDA [$1D]: el despachador lee aquí el código de cada comando
TEXT_FETCH_PCS = frozenset({"4573", "45E8", "45C8"})  # lecturas de glifos, no de argumentos
PATTERNS = {"ascending": (1, 2, 3, 4, 5, 6), "zeros": (0, 0, 0, 0, 0, 0)}
FRAMES = 8
SKIPPED = range(0xFA, 0xFE)


def interpret_reads(reads: list[tuple[int, str]]) -> int | None:
    """Número de argumentos a partir de las lecturas ``(posición, PC)`` del guion; ``None`` si el motor se bloqueó.

    La posición 0 es el propio comando. Los avances sin lectura (``INC`` del puntero)
    cuentan: se usa la posición de la siguiente captura de comando, no el número de lecturas.
    """
    later = sorted(position for position, pc in reads if position > 0 and pc == COMMAND_FETCH_PC)
    return later[0] - 1 if later else None


def probe_command(call, state: str, command: int, arguments: tuple[int, ...]) -> list[tuple[int, str]]:
    call("state.load", path=state)
    script = bytes([command, *arguments, 0xC7, 0xC7, 0xC7, 0xC7])
    call("cpu.write_memory", memoryType="snesWorkRam", address=SCRIPT_OFFSET, bytes=list(script))
    depth = call("cpu.read_memory", memoryType="snesWorkRam", address=POINTER_STACK_DEPTH, length=1)["bytes"][0]
    pointer = [SCRIPT_OFFSET & 0xFF, SCRIPT_OFFSET >> 8, 0x7E]
    call("cpu.write_memory", memoryType="snesWorkRam", address=POINTER_STACK_BASE + 3 * depth, bytes=pointer)
    call("cpu.write_memory", memoryType="snesWorkRam", address=ACTIVE_POINTER, bytes=pointer)
    call("cpu.write_memory", memoryType="snesWorkRam", address=COMMAND_STATE, bytes=[0, 0])
    handle = call("watch.create", memoryType="snesMemory", address=WRAM_BANK + SCRIPT_OFFSET, length=len(script), access="read", cpuType="snes")["handle"]
    call("run.step_frames", frames=FRAMES)
    events = [e for e in call("watch.list")["events"] if e["handle"] == handle]
    call("watch.delete", handle=handle)
    return [((e["address"] & 0xFFFF) - SCRIPT_OFFSET, e["pcDisplay"].split(":")[-1]) for e in events]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--rom", default=os.environ.get("DARK_LAW_ROM"), help="ROM original (o DARK_LAW_ROM)")
    parser.add_argument("--mesen-bin", default=os.environ.get("MESEN_BIN"), help="Mesen (o MESEN_BIN)")
    parser.add_argument("--state", required=True, help="savestate del intro con el motor parado entre comandos")
    arguments = parser.parse_args(argv)
    if not arguments.rom or not arguments.mesen_bin:
        print("error: pass --rom and --mesen-bin, or set DARK_LAW_ROM and MESEN_BIN", file=sys.stderr)
        return 2
    print("cmd  ascending  zeros   (n = arguments, '-' = the engine blocked)")
    for command in range(0xC0, 0x100):
        if command in SKIPPED:
            continue
        results = []
        for pattern in PATTERNS.values():
            # una sesión nueva por medición: acumular watches y cargas en una sola sesión la dejó colgada
            with emulator_session(Path(arguments.rom), arguments.mesen_bin) as (call, _):
                results.append(interpret_reads(probe_command(call, arguments.state, command, pattern)))
        shown = ["-" if r is None else str(r) for r in results]
        note = "" if results[0] == results[1] else "  <-- the patterns disagree"
        print(f"{command:02X}   {shown[0]:>8}  {shown[1]:>5}{note}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
