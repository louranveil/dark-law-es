#!/usr/bin/env python3
"""Dibujo forzado de mensajes: mide el tipo de ventana de cualquier mensaje sin llegar a él jugando.

El recorrido de ``tools/tour_messages.py`` solo alcanza los mensajes que la ruta dispara. Este módulo parte de un
estado guardado del campo (``field-start.mss``) y, para cada entrada del mapa de tramos, hace lo que hace el motor
al empezar un script: escribe el puntero largo del blob (en la ROM, sin copiarlo) en el nivel actual de la pila de
punteros de script, pone el despachador en el modo de ejecución (``$0AC3`` = 2, estado ``$0AC4``-``$0ACA`` a cero) y el
bucle principal del campo en el modo de evento (``$40`` = 2). El motor dibuja el blob con su propio código: el
registro de muestras es el del recorrido y lo analiza ``tour_messages.py report`` y ``budgets``. Una pulsación de A
cada pocos fotogramas pasa las esperas de tecla. El blob ha terminado cuando el despachador vuelve al modo 1.

Lo que sale de la RAM, nunca de la pantalla: por cada tramo el tipo de ventana (``$0A4C``) y los contadores de celdas
al dibujarse; por cada entrada los tipos de ventana vistos en cualquier muestra (``C2`` abre el tipo 3 sin dibujar
texto) y cómo terminó (``finished`` o ``timeout``).

Uso::

    python tools/force_messages.py run --rom <rom.sfc> --map <mapa.json> --savestates <dir> --mesen-bin <Mesen.exe> \\
        --table E7362B --out <registro.json> [--shard 0/4] [--resume]
    python tools/force_messages.py plan --map <mapa.json> --table E7362B

La salida de ``run`` es un registro de ``tour_messages.py`` con una clave ``forced`` más. Requiere el paquete
mesen_probe y ``MESEN_FOR_AI_DIR``. Códigos de salida: 0 bien, 1 falló el emulador, 2 uso incorrecto.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import tour_messages as tour

FIELD_MODE = 0x40  # modo del bucle principal del campo: 1 caminando, 2 ejecutando un evento (C3:7B3A, D1:0000)
RUN_MODE = 0x0AC3  # modo del despachador ($D1:0000 salta por tabla): 1 espera un evento, 2 ejecuta el script del nivel superior
RUNNING = 2
STATE_FIRST, STATE_LENGTH = 0x0AC4, 7  # autómata de comandos $0AC4-$0ACA, a cero al empezar un script ($D1:0257-$D1:026C)
DEFAULT_STATE = "field-start.mss"
DEFAULT_MAX_FRAMES = 900
MAX_FAILURES = 20  # fallos del emulador tolerados en una ejecución antes de parar
SESSION_ATTEMPTS = 8  # con varias sesiones a la vez el puerto del puente choca más a menudo que con una (WinError 10048)
PRESS_PERIOD, PRESS_HOLD = 12, 2  # A cada 12 fotogramas, 2 pulsado


class PlanError(ValueError):
    """La selección de entradas no es válida."""


@dataclass(frozen=True)
class ForcedEntry:
    entry_id: str
    address: int
    message_id: int | None  # índice de la primera tabla que lo apunta (los mensajes ``T0`` tienen id igual al índice)

    @property
    def label(self) -> str:
        return self.entry_id


def entry_message_id(slots: list[str]) -> int | None:
    """El índice del primer puntero de ``slots`` (``E7362B#3`` es 3); ``None`` si no hay."""
    for slot in slots:
        _, _, number = slot.partition("#")
        if number.isdigit():
            return int(number)
    return None


def parse_shard(text: str) -> tuple[int, int]:
    """``2/4`` es la tercera de cuatro partes (``0``-based)."""
    try:
        part, _, count = text.partition("/")
        index, total = int(part), int(count)
    except ValueError as error:
        raise PlanError(f"bad shard {text!r}: use INDEX/COUNT such as 0/4") from error
    if total < 1 or not 0 <= index < total:
        raise PlanError(f"bad shard {text!r}: INDEX must be below COUNT")
    return index, total


def plan_entries(
    document: dict,
    tables: list[str] | None = None,
    ids: list[str] | None = None,
    shard: tuple[int, int] = (0, 1),
    skip: set[str] | None = None,
) -> list[ForcedEntry]:
    """Entradas del mapa que se van a forzar, por dirección.

    ``tables`` filtra por tabla de origen (``E7362B``: la dirección sin los dos puntos, como en ``slots``), ``ids`` por
    dirección de blob (``E7:379B``), ``skip`` quita las ya hechas y ``shard`` reparte el resto en partes alternas.
    """
    if document.get("format") != 1:
        raise PlanError("unsupported map format")
    wanted_tables = {table.upper().replace(":", "") for table in tables or []}
    wanted_ids = {entry_id.upper() for entry_id in ids or []}
    chosen: list[ForcedEntry] = []
    for entry in document["entries"]:
        if wanted_ids and entry["id"].upper() not in wanted_ids:
            continue
        if wanted_tables and not any(slot.partition("#")[0].upper() in wanted_tables for slot in entry["slots"]):
            continue
        if skip and entry["id"] in skip:
            continue
        chosen.append(ForcedEntry(entry["id"], tour.parse_address(entry["address"]), entry_message_id(entry["slots"])))
    chosen.sort(key=lambda item: item.address)
    index, total = shard
    return chosen[index::total]


def force_script(call: tour.ToolCaller, address: int, message_id: int | None = None) -> None:
    """Empieza el script de ``address`` en el nivel actual de la pila: lo que el motor hace al resolver un mensaje."""
    depth = call("cpu.read_memory", memoryType="snesWorkRam", address=tour.STACK_DEPTH, length=1)["bytes"][0]
    level = tour.STACK_BASE + 3 * depth
    call("cpu.write_memory", memoryType="snesWorkRam", address=level, bytes=[address & 0xFF, address >> 8 & 0xFF, address >> 16])
    if message_id is not None:
        call("cpu.write_memory", memoryType="snesWorkRam", address=tour.MESSAGE_ID, bytes=[message_id & 0xFF, message_id >> 8 & 0xFF])
    call("cpu.write_memory", memoryType="snesWorkRam", address=tour.WINDOW_TYPE, bytes=[0])  # ventana cerrada: solo el motor la abre
    call("cpu.write_memory", memoryType="snesWorkRam", address=RUN_MODE, bytes=[RUNNING])
    call("cpu.write_memory", memoryType="snesWorkRam", address=STATE_FIRST, bytes=[0] * STATE_LENGTH)
    call("cpu.write_memory", memoryType="snesWorkRam", address=FIELD_MODE, bytes=[RUNNING])


@dataclass
class ForcedResult:
    entry: ForcedEntry
    outcome: str  # ``finished`` o ``timeout``
    frames: int
    types_seen: list[int]  # tipos de ventana abiertos por el motor (sin el 0 de la ventana cerrada)
    samples: list[tour.Sample]

    def to_json(self) -> dict:
        return {
            "id": self.entry.entry_id,
            "address": tour.format_address(self.entry.address),
            "message_id": self.entry.message_id,
            "outcome": self.outcome,
            "frames": self.frames,
            "types_seen": self.types_seen,
        }


def read_sample_and_mode(call: tour.ToolCaller, frame: int) -> tuple[tour.Sample, int]:
    """Una muestra y el modo del despachador con una sola lectura (cada llamada al puente cuesta unos 15 ms).

    No lee ``$1D``-``$1F``: el recorrido ya mostró que no es fiable fuera del bucle de texto y el análisis usa la pila de
    punteros, así que ``direct_pointer`` queda a cero en estas muestras.
    """
    block = bytes(call("cpu.read_memory", memoryType="snesWorkRam", address=tour.BLOCK_START, length=tour.BLOCK_LENGTH)["bytes"])
    return tour.decode_sample(frame, block, bytes(3)), block[RUN_MODE - tour.BLOCK_START]


def drive_entry(
    call: tour.ToolCaller,
    entry: ForcedEntry,
    savestate: Path,
    frame_offset: int = 0,
    max_frames: int = DEFAULT_MAX_FRAMES,
    poll: int = 1,
    on_sample=None,
) -> ForcedResult:
    """Carga el estado, fuerza el blob y avanza hasta que el despachador vuelve al modo 1 o se agotan ``max_frames``."""
    call("state.load", path=str(savestate))
    force_script(call, entry.address, entry.message_id)
    recorder = tour.Recorder()
    held = False
    frame = 0
    outcome = "timeout"
    while frame < max_frames:
        want = frame % PRESS_PERIOD < PRESS_HOLD  # la pulsación de A se decide cada ``poll`` fotogramas
        if want != held:
            call("input.set", buttons={"a": want})
            held = want
        chunk = min(poll, max_frames - frame)
        call("run.step_frames", frames=chunk)
        frame += chunk
        sample, mode = read_sample_and_mode(call, frame_offset + frame)
        recorder.add(sample)
        if on_sample is not None:
            on_sample(sample)
        if mode != RUNNING:
            outcome = "finished"
            break
    if held:
        call("input.set", buttons={"a": False})
    types = sorted({sample.window_type for sample in recorder.samples} - {0})  # 0 es la ventana cerrada con que empieza
    return ForcedResult(entry, outcome, frame, types, recorder.samples)


def read_forced(path: Path) -> tuple[dict, list[tour.Sample]]:
    """Lee un registro de ``run`` (con la lista ``forced``) para reanudarlo."""
    document, samples = tour.read_log(path)
    document.setdefault("forced", [])
    return document, samples


def run_command(arguments: argparse.Namespace) -> int:
    from smoke_emulator import emulator_session  # importación tardía: solo ``run`` necesita el emulador

    try:
        document = json.loads(arguments.map.read_text(encoding="utf-8"))
        index = tour.RunIndex(document)
        shard = parse_shard(arguments.shard)
        previous: dict | None = None
        samples: list[tour.Sample] = []
        if arguments.resume and arguments.out and arguments.out.is_file():
            previous, samples = read_forced(arguments.out)
        done = {item["id"] for item in previous["forced"]} if previous else set()
        entries = plan_entries(document, arguments.table, arguments.entry, shard, done)
        if arguments.limit:
            entries = entries[: arguments.limit]
    except (tour.RouteError, PlanError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    savestate = (arguments.savestates / arguments.state).resolve() if arguments.savestates else None
    if savestate is None or not savestate.is_file():
        print(f"error: savestate not found: {savestate} (pass --savestates)", file=sys.stderr)
        return 2
    if not arguments.mesen_bin or not Path(arguments.mesen_bin).is_file() or not arguments.rom.is_file():
        print("error: give an existing --rom and --mesen-bin (or MESEN_BIN)", file=sys.stderr)
        return 2
    forced: list[dict] = list(previous["forced"]) if previous else []
    recorder = tour.Recorder()
    for sample in samples:
        recorder.add(sample)
    offset = recorder.frames
    checks: list[dict] | None = list(previous.get("buffer_checks", [])) if previous and arguments.check_buffers else None
    route = {"name": "forced"}

    def save() -> None:
        if arguments.out:
            tour.write_log(arguments.out, recorder, route, arguments.rom, checks, {"forced": forced, "savestate": arguments.state})

    started = time.time()
    attempt = 0
    failures: dict[str, int] = {}
    status = 0
    while entries and attempt < SESSION_ATTEMPTS:
        try:
            with emulator_session(arguments.rom, arguments.mesen_bin) as (call, _):
                checker = tour.make_checker(call, index, arguments.rom) if arguments.check_buffers else None
                while entries:
                    entry = entries[0]
                    result = drive_entry(call, entry, savestate, offset, arguments.max_frames, arguments.poll, checker)
                    for sample in result.samples:
                        recorder.add(sample)
                    offset += result.frames + 1
                    forced.append(result.to_json())
                    if checker is not None:
                        checks = list(checker.results.values())
                    entries.pop(0)
                    if len(forced) % arguments.save_every == 0:
                        save()
                        print(f"{len(forced)} entries forced, {len(entries)} left, {time.time() - started:.0f} s", flush=True)
            attempt = 0
        except OSError as error:  # el puerto del puente local lo puede ocupar otra sesión (Windows, 10048)
            attempt += 1
            print(f"emulator session failed (attempt {attempt}/{SESSION_ATTEMPTS}): {error}", file=sys.stderr)
            time.sleep(3 + random.random() * 9)  # al azar, para que las sesiones paralelas no vuelvan a coincidir
        except Exception as error:  # un fallo del emulador no es un error de uso
            # La entrada que lo provocó se repite en una sesión nueva; si vuelve a fallar se anota como ``error`` y se sigue.
            entry = entries[0]
            failures[entry.entry_id] = failures.get(entry.entry_id, 0) + 1
            print(f"emulator failed on {entry.entry_id} ({failures[entry.entry_id]}/2): {type(error).__name__}: {error}", file=sys.stderr)
            if failures[entry.entry_id] >= 2:
                forced.append({"id": entry.entry_id, "address": tour.format_address(entry.address), "message_id": entry.message_id,
                               "outcome": "error", "frames": 0, "types_seen": [], "error": f"{type(error).__name__}: {error}"[:200]})
                entries.pop(0)
            if sum(failures.values()) > MAX_FAILURES:
                print("error: too many emulator failures", file=sys.stderr)
                status = 1
                break
    save()
    if entries and status == 0:
        status = 1
    visits = tour.track_visits(recorder.samples, index)
    unfinished = [item["id"] for item in forced if item["outcome"] != "finished"]
    print(f"forced {len(forced)} entries, {recorder.frames} frames, {len(unfinished)} did not finish")
    print(tour.format_report(visits, index))
    return status


def summarize_forced(documents: list[dict], index: tour.RunIndex, visits: list[tour.Visit]) -> dict:
    """Resumen de uno o varios registros de ``run``: cómo terminó cada entrada, por tabla, y qué tipos de ventana se vieron.

    Una entrada forzada en dos registros cuenta una vez (la primera). Los tramos y sus tipos salen de ``visits``
    (``tour_messages.track_visits``); los tipos por entrada, de la lista ``forced`` de los registros.
    """
    forced: dict[str, dict] = {}
    for document in documents:
        for item in document.get("forced", []):
            forced.setdefault(item["id"], item)
    table_of = {entry["id"]: entry["slots"][0].partition("#")[0] for entry in index.document["entries"] if entry["slots"]}
    by_table: dict[str, dict[str, int]] = {}
    type_sets: dict[str, list[str]] = {}
    for entry_id, item in forced.items():
        row = by_table.setdefault(table_of.get(entry_id, "?"), {"entries": 0, "finished": 0, "timeout": 0, "error": 0})
        row["entries"] += 1
        row[item["outcome"]] += 1
        type_sets.setdefault(",".join(str(kind) for kind in item["types_seen"]) or "none", []).append(entry_id)
    drawn: dict[tuple[str, int], tour.Visit] = {}
    for visit in visits:
        if visit.drawn_frame is not None:
            drawn.setdefault(visit.run.key, visit)
    runs_by_table: dict[str, dict[str, int]] = {}
    for key, visit in drawn.items():
        table = table_of.get(key[0], "?")
        counts = runs_by_table.setdefault(table, {})
        counts[str(visit.window_type)] = counts.get(str(visit.window_type), 0) + 1
    forced_runs = [info for info in index.runs.values() if info.entry_id in forced]
    missed = [info for info in forced_runs if info.key not in drawn]
    return {
        "entries forced": len(forced),
        "by table": dict(sorted(by_table.items())),
        "runs drawn by table and window type": dict(sorted(runs_by_table.items())),
        "window types opened per entry": {kinds: len(ids) for kinds, ids in sorted(type_sets.items())},
        "entries opening a window type other than 1 or 2": {kinds: ids for kinds, ids in type_sets.items() if set(kinds.split(",")) - {"1", "2", "none"}},
        "runs of forced entries": len(forced_runs),
        "runs of forced entries not drawn": [{"id": info.entry_id, "run": info.number} for info in missed],
        "entries that did not finish": sorted(entry_id for entry_id, item in forced.items() if item["outcome"] != "finished"),
    }


def summary_command(arguments: argparse.Namespace) -> int:
    try:
        index = tour.RunIndex(json.loads(arguments.map.read_text(encoding="utf-8")))
        documents: list[dict] = []
        visits: list[tour.Visit] = []
        for log in arguments.log:
            document, samples = read_forced(log)
            documents.append(document)
            visits += tour.track_visits(samples, index)
    except (ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(summarize_forced(documents, index, visits), indent=1))
    return 0


def plan_command(arguments: argparse.Namespace) -> int:
    try:
        document = json.loads(arguments.map.read_text(encoding="utf-8"))
        entries = plan_entries(document, arguments.table, arguments.entry, parse_shard(arguments.shard))
    except (PlanError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    for entry in entries:
        print(f"{entry.entry_id} id {entry.message_id}")
    print(f"{len(entries)} entries")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    def selection(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--map", type=Path, required=True, help="mapa JSON de build_marker_rom.py")
        sub.add_argument("--table", action="append", help="solo las entradas de esta tabla (por ejemplo E7362B); se puede repetir")
        sub.add_argument("--entry", action="append", help="solo esta entrada (por ejemplo E7:379B); se puede repetir")
        sub.add_argument("--shard", default="0/1", help="INDICE/TOTAL: reparte las entradas en partes para varias sesiones")

    run = commands.add_parser("run", help="fuerza el dibujo de las entradas en el emulador y escribe el registro")
    selection(run)
    run.add_argument("--rom", type=Path, required=True, help="ROM de marcadores o la original (con su mapa)")
    run.add_argument("--savestates", type=Path, help="carpeta de los estados guardados (fuera del repositorio)")
    run.add_argument("--state", default=DEFAULT_STATE, help="estado de partida (por defecto field-start.mss)")
    run.add_argument("--mesen-bin", default=os.environ.get("MESEN_BIN"), help="ejecutable de Mesen (o MESEN_BIN)")
    run.add_argument("--poll", type=int, default=2, help="leer la RAM cada N fotogramas (1 o 2; 2 es la mitad de lento de leer y no perdió tramos en la prueba)")
    run.add_argument("--max-frames", type=int, default=DEFAULT_MAX_FRAMES, help="fotogramas máximos por entrada")
    run.add_argument("--limit", type=int, help="solo las primeras N entradas de la selección")
    run.add_argument("--out", type=Path, help="registro JSON")
    run.add_argument("--resume", action="store_true", help="seguir un registro --out existente, sin repetir sus entradas")
    run.add_argument("--save-every", type=int, default=20, help="guardar el registro cada N entradas")
    run.add_argument("--check-buffers", action="store_true", help="comprobar en la WRAM las letras de los marcadores dibujados")
    summary = commands.add_parser("summary", help="resumen de uno o varios registros de run, sin emulador")
    summary.add_argument("--map", type=Path, required=True)
    summary.add_argument("--log", type=Path, action="append", required=True)
    plan = commands.add_parser("plan", help="lista las entradas que se forzarían, sin emulador")
    selection(plan)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.command == "run" and (arguments.poll < 1 or arguments.max_frames < 1 or arguments.save_every < 1):
        print("error: --poll, --max-frames and --save-every must be at least 1", file=sys.stderr)
        return 2
    return {"run": run_command, "plan": plan_command, "summary": summary_command}[arguments.command](arguments)


if __name__ == "__main__":
    sys.exit(main())
