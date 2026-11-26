#!/usr/bin/env python3
"""Recorrido guiado por RAM de los mensajes de una ROM de marcadores (etapa 3 del pipeline).

Conduce MesenCE con una ruta (datos: un estado guardado o un reinicio y una lista de pulsaciones) y, tras cada
fotograma, lee la RAM de trabajo, nunca la pantalla: el tipo de ventana (``$0A4C``), los contadores de celdas
(``$0A45``, ``$0A47``, ``$0A49``), el identificador de mensaje (``$0AC1``), la profundidad de la pila de punteros
de script (``$0A8D``), el puntero del nivel superior (3 bytes por nivel desde ``$0A8F``) y el puntero activo
(``$1D``-``$1F``). Con el mapa de ``tools/build_marker_rom.py`` el puntero dice qué tramo se está dibujando: mientras
el motor dibuja un tramo el puntero del nivel superior apunta a su inicio y, al terminar, al comando que sigue
(su fin); ambos son direcciones únicas del tramo. Una *visita* es una racha de fotogramas con el puntero en un
tramo; se anota el tipo de ventana y los contadores en el fotograma en que el puntero llega al fin del tramo
(el dibujo ya está hecho), que es la medida de cuántas celdas ocupó el texto.

Formato de una ruta (JSON o los diccionarios de ``ROUTES``)::

    {"name": "field", "start": {"state": "field-start.mss"},          # o {"reset": 600}: arranque en frío
     "steps": [{"press": ["down"], "hold": 8, "release": 12, "times": 18},
               {"wait": 30}]}

Uso::

    python tools/tour_messages.py run --rom <marcadores.sfc> --map <marcadores.sfc.map.json> --route field \\
        --savestates <dir> --mesen-bin <Mesen.exe> --out <registro.json>
    python tools/tour_messages.py report --map <mapa.json> --log <registro.json> [--log <otro.json>]

``--poll N`` lee la RAM cada N fotogramas. Con 1 o 2 no se pierde ningún tramo; con 4 se perdió una página que lleva
inmediatamente comandos detrás (el puntero solo se queda en el fin del tramo unos fotogramas), así que un tramo no
alcanzado con N > 2 puede ser un fallo del muestreo y no de la ruta.

Requiere el paquete mesen_probe y ``MESEN_FOR_AI_DIR`` para ``run``; ``report`` no usa el emulador. Los estados
guardados contienen memoria del juego: viven fuera del repositorio y no se versionan. Códigos de salida: 0 bien,
1 falló el emulador o la ruta, 2 uso incorrecto.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

LOG_FORMAT = 1
STARTUP_ATTEMPTS = 3
WINDOW_TYPE = 0x0A4C
SLOT_COUNTERS = (0x0A45, 0x0A47, 0x0A49)
MESSAGE_ID = 0x0AC1  # 16 bits
STACK_DEPTH = 0x0A8D
STACK_BASE = 0x0A8F  # 3 bytes por nivel
COMMAND_STATE = (0x0AC4, 0x0AC5)
DIRECT_POINTER = 0x1D  # 3 bytes
BLOCK_START = 0x0A3C
BLOCK_LENGTH = 0x94  # llega hasta $0AD0
BUTTONS = frozenset({"up", "down", "left", "right", "a", "b", "x", "y", "l", "r", "start", "select"})
# Qué contador de celdas lee el bucle de cada tipo de ventana (docs/re/window-types.md): solo los tipos 1 y 2 están verificados.
COUNTER_OF_TYPE = {1: 0, 2: 1}
# Celdas por página de esos dos tipos, leídas del código y comprobadas con los espigones (docs/re/window-types.md): se usan como
# respaldo cuando el recorrido no ha dibujado una regla en ese tipo; con una regla el límite se mide.
CODE_SLOT_LIMITS = {1: 24, 2: 32}
LETTERS_PER_SLOT = 2  # la ficha F9 dibuja dos letras por celda
# El comando que abre la página fija el tipo de ventana: el manejador de ``C0`` ($D1:0536 -> $D1:2B62) escribe 1 en $0A4C en
# $D1:2BAE y el de ``C1`` ($D1:056C -> $D1:2BC2) escribe 2 en $D1:2C27 (leído del código; los tramos dibujados lo confirman).
OPENER_TYPE = {"C0": 1, "C1": 2}
SKELETON_TOKEN = re.compile(r"<([0-9A-F]{2})(?: [0-9A-F]{2})*>|\{(\d+)\}")
ROW_START = {1: 12, 2: 16}  # celda en que ``C3`` empieza la segunda línea (docs/re/window-types.md)

ToolCaller = Callable[..., dict]


class RouteError(ValueError):
    """La ruta no sigue el formato."""


# Rutas incluidas. Los números de pasos y fotogramas salen de docs/re/window-types.md (campo) y de docs/re/text-engine.md (intro).
ROUTES: dict[str, dict] = {
    "field": {
        "name": "field",
        "start": {"state": "field-start.mss"},
        "steps": [
            {"press": ["down"], "hold": 8, "release": 12, "times": 18},
            {"press": ["left"], "hold": 8, "release": 12, "times": 16},
            {"wait": 60},
            {"press": ["a"], "hold": 4, "release": 40, "times": 12},
        ],
    },
    "intro-cold": {
        "name": "intro-cold",
        "description": "arranque en frío, Start en el título, A en el menú y A cada 60 fotogramas (300 veces) por el intro",
        "start": {"reset": 600},
        "steps": [
            {"press": ["start"], "hold": 5, "release": 60},
            {"press": ["a"], "hold": 5, "release": 400},
            {"press": ["a"], "hold": 4, "release": 56, "times": 300},
        ],
    },
    "intro": {
        "name": "intro",
        "start": {"state": "intro-300-years.mss"},
        "steps": [{"press": ["a"], "hold": 4, "release": 56, "times": 30}],
    },
}


def validate_route(route: dict) -> dict:
    """Comprueba el formato de la ruta y la devuelve; falla con ``RouteError`` si no lo cumple."""
    if not isinstance(route, dict) or set(route) - {"name", "description", "start", "steps"}:
        raise RouteError("a route is an object with name, start and steps")
    start = route.get("start")
    if not isinstance(start, dict) or len(start) != 1 or next(iter(start)) not in ("state", "reset"):
        raise RouteError("start must be {'state': <file>} or {'reset': <frames>}")
    if "reset" in start and not (isinstance(start["reset"], int) and start["reset"] >= 0):
        raise RouteError("start.reset must be a number of frames")
    if "state" in start and not isinstance(start["state"], str):
        raise RouteError("start.state must be a file name")
    steps = route.get("steps")
    if not isinstance(steps, list):
        raise RouteError("steps must be a list")
    for number, step in enumerate(steps):
        where = f"step {number}"
        if not isinstance(step, dict):
            raise RouteError(f"{where}: must be an object")
        if "wait" in step:
            if set(step) != {"wait"} or not (isinstance(step["wait"], int) and step["wait"] > 0):
                raise RouteError(f"{where}: wait takes only a positive frame count")
        elif "press" in step:
            if set(step) - {"press", "hold", "release", "times"}:
                raise RouteError(f"{where}: press takes press, hold, release and times")
            buttons = step["press"]
            if not isinstance(buttons, list) or not buttons or not set(buttons) <= BUTTONS:
                raise RouteError(f"{where}: press must list buttons among {sorted(BUTTONS)}")
            if "hold" not in step:
                raise RouteError(f"{where}: press needs hold")
            for name, minimum in (("hold", 1), ("release", 0), ("times", 1)):
                if name in step and not (isinstance(step[name], int) and step[name] >= minimum):
                    raise RouteError(f"{where}: {name} must be an integer of at least {minimum}")
        else:
            raise RouteError(f"{where}: a step is a wait or a press")
    return route


def walk_route(seed: int, moves: int, state: str = "field-start.mss", interact_every: int = 4) -> dict:
    """Ruta de paseo al azar, determinista por ``seed``: cada paso mantiene una dirección 8 fotogramas y la suelta 12 (como la
    ruta de ``field``) y cada ``interact_every`` pasos pulsa A para abrir o avanzar mensajes. Es una exploración sin mapa."""
    import random

    generator = random.Random(seed)
    steps: list[dict] = []
    for number in range(1, moves + 1):
        steps.append({"press": [generator.choice(("up", "down", "left", "right"))], "hold": 8, "release": 12})
        if interact_every and number % interact_every == 0:
            steps.append({"press": ["a"], "hold": 3, "release": 25})
    return {"name": f"walk-{seed}", "description": f"random walk of {moves} moves, seed {seed}", "start": {"state": state}, "steps": steps}


def route_frames(route: dict) -> int:
    """Fotogramas que dura la ruta tras el arranque."""
    total = 0
    for step in route["steps"]:
        total += step["wait"] if "wait" in step else (step["hold"] + step.get("release", 0)) * step.get("times", 1)
    return total


@dataclass(frozen=True)
class Sample:
    """Lo que se lee de la RAM tras un fotograma."""

    frame: int
    window_type: int
    slots: tuple[int, int, int]  # $0A45, $0A47, $0A49
    message_id: int
    depth: int
    top_pointer: int  # puntero largo del nivel superior de la pila de scripts
    direct_pointer: int  # $1D-$1F
    state: tuple[int, int]  # $0AC4, $0AC5

    def key(self) -> tuple:
        return (self.window_type, self.slots, self.message_id, self.depth, self.top_pointer, self.direct_pointer, self.state)

    def to_row(self) -> list:
        return [self.frame, self.window_type, *self.slots, self.message_id, self.depth, self.top_pointer, self.direct_pointer, *self.state]

    @classmethod
    def from_row(cls, row: list) -> "Sample":
        frame, window_type, *rest = row
        return cls(frame, window_type, (rest[0], rest[1], rest[2]), rest[3], rest[4], rest[5], rest[6], (rest[7], rest[8]))


def decode_sample(frame: int, block: bytes, direct: bytes) -> Sample:
    """Una muestra a partir del bloque de WRAM que empieza en ``BLOCK_START`` y los tres bytes de ``$1D``."""
    if len(block) < BLOCK_LENGTH or len(direct) < 3:
        raise ValueError("the memory read is shorter than requested")

    def byte(address: int) -> int:
        return block[address - BLOCK_START]

    depth = byte(STACK_DEPTH)
    level = STACK_BASE - BLOCK_START + 3 * depth
    if level + 3 > len(block):
        raise ValueError(f"script pointer stack depth {depth} is outside the sampled block")
    return Sample(
        frame,
        byte(WINDOW_TYPE),
        (byte(SLOT_COUNTERS[0]), byte(SLOT_COUNTERS[1]), byte(SLOT_COUNTERS[2])),
        byte(MESSAGE_ID) | byte(MESSAGE_ID + 1) << 8,
        depth,
        int.from_bytes(block[level : level + 3], "little"),
        int.from_bytes(direct[:3], "little"),
        (byte(COMMAND_STATE[0]), byte(COMMAND_STATE[1])),
    )


def read_sample(call: ToolCaller, frame: int) -> Sample:
    block = bytes(call("cpu.read_memory", memoryType="snesWorkRam", address=BLOCK_START, length=BLOCK_LENGTH)["bytes"])
    direct = bytes(call("cpu.read_memory", memoryType="snesWorkRam", address=DIRECT_POINTER, length=3)["bytes"])
    return decode_sample(frame, block, direct)


class Recorder:
    """Guarda solo las muestras que cambian respecto a la anterior (el registro sigue siendo exacto por fotograma)."""

    def __init__(self) -> None:
        self.samples: list[Sample] = []
        self.frames = 0

    def add(self, sample: Sample) -> None:
        self.frames = sample.frame
        if not self.samples or self.samples[-1].key() != sample.key():
            self.samples.append(sample)


def execute_route(
    call: ToolCaller, route: dict, savestates: Path | None = None, poll: int = 1, on_sample: Callable[[Sample], None] | None = None
) -> Recorder:
    """Ejecuta la ruta y lee la RAM cada ``poll`` fotogramas (1: cada uno). ``call`` es la herramienta del emulador.

    ``on_sample`` se llama con cada muestra justo después de leerla, con el emulador parado en ese fotograma.
    """
    validate_route(route)
    recorder = Recorder()

    def record(sample: Sample) -> None:
        recorder.add(sample)
        if on_sample is not None:
            on_sample(sample)

    frame = 0
    start = route["start"]
    if "state" in start:
        if savestates is None:
            raise RouteError("the route starts from a savestate: pass the savestates directory")
        path = (savestates / start["state"]).resolve()
        if not path.is_file():
            raise RouteError(f"savestate not found: {path}")
        call("state.load", path=str(path))
    elif start["reset"] > 0:
        call("run.step_frames", frames=start["reset"], reset=True)
    else:
        call("session.reset")
    record(read_sample(call, 0))

    def advance(frames: int) -> None:
        """Avanza ``frames`` fotogramas en bloques de ``poll`` y lee la RAM al final de cada bloque."""
        nonlocal frame
        remaining = frames
        while remaining > 0:
            chunk = min(poll, remaining)
            call("run.step_frames", frames=chunk)
            frame += chunk
            remaining -= chunk
            record(read_sample(call, frame))

    for step in route["steps"]:
        if "wait" in step:
            advance(step["wait"])
            continue
        buttons = step["press"]
        for _ in range(step.get("times", 1)):
            call("input.set", buttons={name: True for name in buttons})
            advance(step["hold"])
            call("input.set", buttons={name: False for name in buttons})
            advance(step.get("release", 0))
    return recorder


# Direcciones de la ROM de la tabla de búferes de tiles por celda de cada bucle de texto (docs/re/latin-font-spike.md y window-types.md).
BUFFER_TABLES = {1: 0xD146DB, 2: 0xD148B3}
BUFFER_SLOTS = {1: 24, 2: 32}


class BufferChecker:
    """Comprueba en la WRAM que las celdas de un marcador dibujado contienen las letras del marcador (los tiles de la fuente).

    Es la lectura del texto sin mirar la pantalla: la celda ``k`` del tipo de ventana ``t`` tiene su búfer de tiles en la dirección
    ``k``-ésima de ``BUFFER_TABLES[t]`` (32 bytes arriba y 32 a ``+0x100``) y el gancho copia ahí los tiles de las dos letras. El
    marcador ocupa las últimas celdas dibujadas: la primera es el contador de la ventana menos las celdas del marcador.
    """

    def __init__(self, call: ToolCaller, index: "RunIndex", rom: bytes, letters: str, font: bytes):
        from script_format import cpu_to_offset  # el módulo del formato ya lo usa el resto de herramientas

        self.call, self.index, self.letters, self.font = call, index, letters, font
        self.buffers = {
            kind: [int.from_bytes(rom[cpu_to_offset(table) + 2 * slot : cpu_to_offset(table) + 2 * slot + 2], "little") for slot in range(BUFFER_SLOTS[kind])]
            for kind, table in BUFFER_TABLES.items()
        }
        self.results: dict[tuple[str, int], dict] = {}

    def letter(self, char: str) -> bytes:
        position = self.letters.index(char)
        return self.font[32 * position : 32 * position + 32]

    def __call__(self, sample: Sample) -> None:
        run = self.index.lookup(sample.top_pointer)
        if run is None or sample.top_pointer != run.end or run.key in self.results or run.marker is None or run.ruler:
            return
        if sample.window_type not in self.buffers:
            return
        bad = []
        pairs = len(run.marker) // 2
        first = sample.slots[COUNTER_OF_TYPE[sample.window_type]] - pairs  # una página puede traer tramos antes del de este marcador
        if first < 0:
            self.results[run.key] = {"id": run.entry_id, "run": run.number, "marker": run.marker, "window_type": sample.window_type, "bad_slots": list(range(pairs))}
            return
        for number in range(pairs):
            slot = first + number
            left, right = self.letter(run.marker[2 * number]), self.letter(run.marker[2 * number + 1])
            address = self.buffers[sample.window_type][slot]
            top = bytes(self.call("cpu.read_memory", memoryType="snesWorkRam", address=address, length=32)["bytes"])
            bottom = bytes(self.call("cpu.read_memory", memoryType="snesWorkRam", address=address + 0x100, length=32)["bytes"])
            if top != left[:16] + right[:16] or bottom != left[16:] + right[16:]:
                bad.append(slot)
        self.results[run.key] = {"id": run.entry_id, "run": run.number, "marker": run.marker, "window_type": sample.window_type, "bad_slots": bad}


def make_checker(call: ToolCaller, index: "RunIndex", rom_path: Path) -> BufferChecker:
    """El comprobador de búferes con la fuente y las tablas leídas de la propia ROM de marcadores."""
    import build_custom_font
    from build_latin_probe import FONT_START
    from script_format import cpu_to_offset

    rom = rom_path.read_bytes()
    letters = build_custom_font.LATIN_CHARS
    start = cpu_to_offset(FONT_START)
    return BufferChecker(call, index, rom, letters, rom[start : start + 32 * len(letters)])


@dataclass
class RunInfo:
    entry_id: str
    number: int
    start: int
    end: int
    marker: str | None
    ruler: bool
    letters: int | None
    slots: list[str]
    original_rows: list[int]
    original_bytes: int
    opener: str | None = None  # último ``C0``/``C1`` del esqueleto antes del tramo
    page_commands: tuple[str, ...] = ()  # códigos de los comandos entre ese ``C0``/``C1`` y el tramo (``E7``, ``C3``...)
    predicted_counter: int | None = None  # contador de celdas que debe marcar el tipo de ventana del opener al terminar el tramo (``predict_page_counters``)

    @property
    def key(self) -> tuple[str, int]:
        return (self.entry_id, self.number)


def run_openers(skeleton: str) -> dict[int, str | None]:
    """Para cada tramo del esqueleto, el último ``C0`` o ``C1`` que lo precede (``None`` si no hay ninguno)."""
    openers: dict[int, str | None] = {}
    last: str | None = None
    for match in SKELETON_TOKEN.finditer(skeleton):
        if match.group(2) is not None:
            openers[int(match.group(2))] = last
        elif match.group(1) in OPENER_TYPE:
            last = match.group(1)
    return openers


def run_page_commands(skeleton: str) -> dict[int, tuple[str, ...]]:
    """Para cada tramo, los códigos de los comandos que hay entre el último ``C0``/``C1`` y el tramo."""
    commands: dict[int, tuple[str, ...]] = {}
    since: list[str] = []
    for match in SKELETON_TOKEN.finditer(skeleton):
        if match.group(2) is not None:
            commands[int(match.group(2))] = tuple(since)
        elif match.group(1) in OPENER_TYPE:
            since = []
        else:
            since.append(match.group(1))
    return commands


def predict_page_counters(skeleton: str, rows_by_run: dict[int, list[int]]) -> dict[int, int | None]:
    """El contador de celdas tras cada tramo, recorriendo el esqueleto como lo hace el motor (modelo de filas de docs/re/message-tour.md).

    ``C0``/``C1`` abren la página (contador a cero y tipo de ventana), ``C3`` salta a la celda de inicio de la segunda línea, ``E5 nn``
    suma ``nn``, un glifo suelto del esqueleto suma una celda y un tramo suma su primera línea y, por cada ``C3`` interno, salta a la
    celda de inicio más esa línea. El contador no pasa del límite de la ventana: el bucle descarta los glifos que no caben. Un tramo sin
    ``C0``/``C1`` antes da ``None``.
    """
    counters: dict[int, int | None] = {}
    kind: int | None = None
    slot = 0
    for match in re.finditer(r"<([0-9A-F]{2})((?: [0-9A-F]{2})*)>|\{(\d+)\}", skeleton):
        if match.group(3) is not None:
            number = int(match.group(3))
            rows = rows_by_run.get(number)
            if kind is None or not rows:
                counters[number] = None
                continue
            limit = CODE_SLOT_LIMITS[kind]
            slot = min(slot + rows[0], limit)
            for row in rows[1:]:
                slot = min(ROW_START[kind] + row, limit)
            counters[number] = slot
            continue
        code = int(match.group(1), 16)
        if match.group(1) in OPENER_TYPE:
            kind, slot = OPENER_TYPE[match.group(1)], 0
        elif code < 0xC0:
            slot += 1
        elif kind is not None and match.group(1) == "C3":
            slot = ROW_START[kind]
        elif kind is not None and match.group(1) == "E5" and match.group(2):
            slot = min(slot + int(match.group(2).split()[0], 16), CODE_SLOT_LIMITS[kind])
    return counters


def parse_address(text: str) -> int:
    bank, _, offset = text.partition(":")
    return int(bank, 16) << 16 | int(offset, 16)


def format_address(address: int) -> str:
    return f"{address >> 16:02X}:{address & 0xFFFF:04X}"


class RunIndex:
    """Los tramos del mapa de la ROM de marcadores, por dirección de inicio y de fin."""

    def __init__(self, document: dict):
        if document.get("format") != 1:
            raise ValueError("unsupported map format")
        self.document = document
        self.runs: dict[tuple[str, int], RunInfo] = {}
        self.by_address: dict[int, RunInfo] = {}
        for entry in document["entries"]:
            openers = run_openers(entry["skeleton"])
            page_commands = run_page_commands(entry["skeleton"])
            counters = predict_page_counters(entry["skeleton"], {run["number"]: run["original_rows"] for run in entry["runs"]})
            for run in entry["runs"]:
                info = RunInfo(
                    entry["id"], run["number"], parse_address(run["start"]), parse_address(run["end"]), run["marker"], run["ruler"], run["letters"],
                    entry["slots"], run["original_rows"], run["original_bytes"],
                    openers.get(run["number"]),
                    page_commands.get(run["number"], ()),
                    counters.get(run["number"]),
                )
                self.runs[info.key] = info
                for address in (info.start, info.end):
                    if address in self.by_address:
                        raise ValueError(f"map is ambiguous: {format_address(address)} is a boundary of two runs")
                    self.by_address[address] = info

    def lookup(self, pointer: int) -> RunInfo | None:
        return self.by_address.get(pointer)


@dataclass
class Visit:
    """Una racha de muestras con el puntero del nivel superior en el inicio o el fin de un mismo tramo."""

    run: RunInfo
    first_frame: int
    last_frame: int
    drawn_frame: int | None = None  # primer fotograma con el puntero en el fin del tramo
    window_type: int | None = None  # en ese fotograma
    message_id: int | None = None
    depth: int | None = None
    slots_at_end: tuple[int, int, int] | None = None
    types_seen: set[int] = field(default_factory=set)

    def to_json(self) -> dict:
        return {
            "id": self.run.entry_id,
            "run": self.run.number,
            "marker": self.run.marker,
            "first_frame": self.first_frame,
            "last_frame": self.last_frame,
            "drawn_frame": self.drawn_frame,
            "window_type": self.window_type,
            "message_id": self.message_id,
            "depth": self.depth,
            "slots": list(self.slots_at_end) if self.slots_at_end else None,
        }


def track_visits(samples: list[Sample], index: RunIndex) -> list[Visit]:
    """Visitas a los tramos del mapa, en orden. Un tramo cuenta como dibujado cuando el puntero llega a su fin."""
    visits: list[Visit] = []
    current: Visit | None = None
    for sample in samples:
        run = index.lookup(sample.top_pointer)
        if run is None:
            current = None
            continue
        if current is None or current.run is not run:
            current = Visit(run, sample.frame, sample.frame)
            visits.append(current)
        current.last_frame = sample.frame
        current.types_seen.add(sample.window_type)
        if sample.top_pointer == run.end and current.drawn_frame is None:
            current.drawn_frame = sample.frame
            current.window_type = sample.window_type
            current.message_id = sample.message_id
            current.depth = sample.depth
            current.slots_at_end = sample.slots
    return visits


def slots_drawn(visit: Visit) -> int | None:
    """Celdas que ocupó el texto del tramo: el contador del tipo de ventana (solo los tipos 1 y 2 están verificados)."""
    if visit.slots_at_end is None or visit.window_type not in COUNTER_OF_TYPE:
        return None
    return visit.slots_at_end[COUNTER_OF_TYPE[visit.window_type]]


def predicted_slots(rows: list[int], window_type: int) -> int | None:
    """Celdas que debería marcar el contador tras dibujar un tramo de líneas ``rows``: ``C3`` salta a la celda de inicio de la segunda línea."""
    if window_type not in ROW_START:
        return None
    return ROW_START[window_type] * (len(rows) - 1) + rows[-1]


def summarize(visits: list[Visit], index: RunIndex) -> dict:
    """Resumen por tipo de ventana y lista de lo que no se alcanzó; ``visits`` puede venir de varios registros."""
    drawn: dict[tuple[str, int], Visit] = {}
    for visit in visits:
        if visit.drawn_frame is not None:
            drawn.setdefault(visit.run.key, visit)
    entry_types: dict[str, set[int]] = {}
    for visit in drawn.values():
        entry_types.setdefault(visit.run.entry_id, set()).add(visit.window_type)
    by_type: dict[int, dict] = {}
    japanese: dict = {"checked": 0, "differ": []}
    opener_types: dict[str, dict[str, int]] = {}
    after_e7: dict[str, dict[str, int]] = {}
    for visit in drawn.values():
        counts = opener_types.setdefault(str(visit.run.opener), {})
        counts[str(visit.window_type)] = counts.get(str(visit.window_type), 0) + 1
        if "E7" in visit.run.page_commands:
            by_opener = after_e7.setdefault(str(visit.run.opener), {})
            by_opener[str(visit.window_type)] = by_opener.get(str(visit.window_type), 0) + 1
    marked_map = any(info.marker is not None for info in index.runs.values())
    for visit in drawn.values():
        stats = by_type.setdefault(
            visit.window_type, {"runs": 0, "max_slots": 0, "unmeasured": 0, "ruler": [], "original_max_row": 0, "original_max_slots": 0}
        )
        stats["runs"] += 1
        stats["original_max_row"] = max(stats["original_max_row"], *visit.run.original_rows)
        stats["original_max_slots"] = max(stats["original_max_slots"], sum(visit.run.original_rows))
        slots = slots_drawn(visit)
        if slots is None:
            stats["unmeasured"] += 1
            continue
        stats["max_slots"] = max(stats["max_slots"], slots)
        if visit.run.ruler:
            stats["ruler"].append({"id": visit.run.entry_id, "run": visit.run.number, "slots": slots, "letters": visit.run.letters})
        elif visit.run.marker is None and not marked_map:  # ROM original: el contador es el del texto japonés, que se compara con las líneas del mapa
            same_type = OPENER_TYPE.get(str(visit.run.opener)) == visit.window_type
            expected = visit.run.predicted_counter if same_type and visit.run.predicted_counter is not None else predicted_slots(visit.run.original_rows, visit.window_type)
            japanese["checked"] += 1
            if expected != slots:
                japanese["differ"].append({"id": visit.run.entry_id, "run": visit.run.number, "measured": slots, "predicted": expected})
    entries = {info.entry_id: info.slots for info in index.runs.values()}
    reached_entries = {key[0] for key in drawn}
    unreached_runs = [info for key, info in index.runs.items() if key not in drawn]
    return {
        "runs in map": len(index.runs),
        "runs drawn": len(drawn),
        "entries in map": len(entries),
        "entries with a drawn run": len(reached_entries),
        "by window type": {str(kind): stats for kind, stats in sorted(by_type.items())},
        "entries with several window types": sorted(entry for entry, kinds in entry_types.items() if len(kinds) > 1),
        "original text checked against the row model": japanese,
        "drawn runs by opening command and window type": opener_types,
        "drawn runs with an E7 between the opening command and the run": after_e7,
        "unreached runs": [
            {"id": info.entry_id, "run": info.number, "slots": info.slots} for info in sorted(unreached_runs, key=lambda i: (i.start, i.number))
        ],
    }


def measured_slot_limits(visits: list[Visit]) -> dict[int, dict]:
    """Celdas por página de cada tipo de ventana: medidas con una regla que se satura, o las del código como respaldo.

    Una regla que escribe más celdas de las que caben y se dibuja con un contador menor mide el límite; si el
    contador llega justo a lo escrito solo da una cota inferior y no cuenta.
    """
    limits: dict[int, dict] = {kind: {"slots": slots, "evidence": "code"} for kind, slots in CODE_SLOT_LIMITS.items()}
    for visit in visits:
        slots = slots_drawn(visit)
        if slots is None or not visit.run.ruler or visit.run.letters is None:
            continue
        if slots < visit.run.letters // LETTERS_PER_SLOT:
            previous = limits.get(visit.window_type)
            if previous and previous["evidence"] == "ruler" and previous["slots"] != slots:
                raise ValueError(f"rulers disagree on the limit of window type {visit.window_type}: {previous['slots']} and {slots}")
            limits[visit.window_type] = {"slots": slots, "evidence": "ruler"}
    return limits


def budgets(visits: list[Visit], index: RunIndex) -> dict:
    """El ``max`` en letras de cada tramo dibujado (celdas por página del tipo de ventana por dos letras), con su evidencia."""
    limits = measured_slot_limits(visits)
    types_of: dict[tuple[str, int], set[int]] = {}
    first: dict[tuple[str, int], Visit] = {}
    for visit in visits:
        if visit.drawn_frame is None:
            continue
        types_of.setdefault(visit.run.key, set()).add(visit.window_type)
        first.setdefault(visit.run.key, visit)
    result: dict[str, dict] = {}
    for key, visit in sorted(first.items(), key=lambda item: (item[1].run.start, item[0][1])):
        kinds = sorted(types_of[key])
        known = [limits[kind] for kind in kinds if kind in limits]
        entry = result.setdefault(key[0], {"slots": visit.run.slots, "runs": {}})
        if len(known) != len(kinds):
            entry["runs"][str(key[1])] = {"window_type": kinds, "max": None, "evidence": "no measured limit for this window type"}
            continue
        limit = min(item["slots"] for item in known)
        entry["runs"][str(key[1])] = {
            "window_type": kinds,
            "max": limit * LETTERS_PER_SLOT,
            "evidence": "measured" if all(item["evidence"] == "ruler" for item in known) else "code",
            "original_rows": visit.run.original_rows,
        }
    for key, info in index.runs.items():
        if key in first or info.opener not in OPENER_TYPE:
            continue
        kind = OPENER_TYPE[info.opener]
        entry = result.setdefault(info.entry_id, {"slots": info.slots, "runs": {}})
        entry["runs"][str(info.number)] = {
            "window_type": [kind],
            "max": limits[kind]["slots"] * LETTERS_PER_SLOT,
            "evidence": f"predicted: the opening command {info.opener} sets window type {kind}",
            "original_rows": info.original_rows,
        }
    return {"slot limits": {str(kind): limit for kind, limit in sorted(limits.items())}, "entries": result}


def format_report(visits: list[Visit], index: RunIndex) -> str:
    summary = summarize(visits, index)
    lines = [
        f"runs in the map: {summary['runs in map']}, drawn: {summary['runs drawn']}",
        f"entries in the map: {summary['entries in map']}, with a drawn run: {summary['entries with a drawn run']}",
    ]
    for kind, stats in summary["by window type"].items():
        lines.append(
            f"window type {kind}: {stats['runs']} runs drawn, largest counter {stats['max_slots']} slots ({stats['max_slots'] * 2} letters), "
            f"{stats['unmeasured']} without a verified counter; original text: widest row {stats['original_max_row']} slots, "
            f"largest page {stats['original_max_slots']} slots"
        )
        for ruler in stats["ruler"]:
            lines.append(f"  ruler {ruler['id']} run {ruler['run']}: {ruler['letters'] // 2} slots written, {ruler['slots']} drawn")
    checked = summary["original text checked against the row model"]
    if checked["checked"]:
        lines.append(
            f"original text: {checked['checked']} runs measured, {checked['checked'] - len(checked['differ'])} agree with the model "
            f"(C3 starts row 2 at slot 12 in type 1 and 16 in type 2); differing: {checked['differ']}"
        )
    lines.append(f"drawn runs by opening command and window type: {summary['drawn runs by opening command and window type']}")
    lines.append(f"drawn runs with an E7 between the opening command and the run: {summary['drawn runs with an E7 between the opening command and the run']}")
    lines.append("drawn runs (first visit of each):")
    seen: set[tuple[str, int]] = set()
    for visit in visits:
        if visit.drawn_frame is None or visit.run.key in seen:
            continue
        seen.add(visit.run.key)
        lines.append(
            f"  {visit.run.entry_id} run {visit.run.number} marker {visit.run.marker or '-'} frame {visit.drawn_frame} "
            f"type {visit.window_type} id {visit.message_id} depth {visit.depth} slots {slots_drawn(visit)} "
            f"original rows {visit.run.original_rows}"
        )
    unreached = summary["unreached runs"]
    lines.append(f"unreached runs: {len(unreached)}")
    shown = 40
    for item in unreached[:shown]:
        lines.append(f"  {item['id']} run {item['run']} ({', '.join(item['slots'])})")
    if len(unreached) > shown:
        lines.append(f"  ... and {len(unreached) - shown} more (use --json for the full list)")
    return "\n".join(lines)


def write_log(path: Path, recorder: Recorder, route: dict, rom: Path, buffer_checks: list[dict] | None = None, extra: dict | None = None) -> None:
    digest = hashlib.sha1(rom.read_bytes()).hexdigest().upper()
    document = {
        "format": LOG_FORMAT,
        "route": route["name"],
        "rom": rom.name,
        "rom_sha1": digest,
        "frames": recorder.frames,
        "columns": ["frame", "window_type", "slot_0A45", "slot_0A47", "slot_0A49", "message_id", "depth", "top_pointer", "direct_pointer", "state_0AC4", "state_0AC5"],
        "samples": [sample.to_row() for sample in recorder.samples],
    }
    if buffer_checks is not None:
        document["buffer_checks"] = buffer_checks
    if extra:
        document.update(extra)  # claves de otras herramientas (por ejemplo ``forced``); ``read_log`` las ignora
    path.write_text(json.dumps(document) + "\n", encoding="utf-8", newline="\n")


def read_log(path: Path) -> tuple[dict, list[Sample]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("format") != LOG_FORMAT:
        raise ValueError(f"{path}: unsupported log format")
    return document, [Sample.from_row(row) for row in document["samples"]]


def load_route(name: str | None, route_file: Path | None) -> dict:
    if route_file is not None:
        return validate_route(json.loads(route_file.read_text(encoding="utf-8")))
    if name not in ROUTES:
        raise RouteError(f"unknown route {name!r}; built-in routes: {', '.join(sorted(ROUTES))}")
    return validate_route(ROUTES[name])


def run_command(arguments: argparse.Namespace) -> int:
    from smoke_emulator import emulator_session  # importación tardía: solo ``run`` necesita el emulador

    try:
        route = load_route(arguments.route, arguments.route_file)
        index = RunIndex(json.loads(arguments.map.read_text(encoding="utf-8")))
    except (RouteError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if not arguments.mesen_bin or not Path(arguments.mesen_bin).is_file() or not arguments.rom.is_file():
        print("error: give an existing --rom and --mesen-bin (or MESEN_BIN)", file=sys.stderr)
        return 2
    recorder = None
    checks: list[dict] | None = None
    for attempt in range(1, STARTUP_ATTEMPTS + 1):
        try:
            with emulator_session(arguments.rom, arguments.mesen_bin) as (call, _):
                checker = make_checker(call, index, arguments.rom) if arguments.check_buffers else None
                recorder = execute_route(call, route, arguments.savestates, arguments.poll, checker)
                checks = None if checker is None else list(checker.results.values())
            break
        except RouteError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        except OSError as error:  # el puerto del puente local lo puede ocupar otra sesión entre elegirlo y usarlo (Windows, 10048)
            print(f"emulator session failed (attempt {attempt}/{STARTUP_ATTEMPTS}): {error}", file=sys.stderr)
            time.sleep(3)
        except Exception as error:  # un fallo del emulador no es un error de uso
            print(f"error: emulator session failed: {type(error).__name__}: {error}", file=sys.stderr)
            return 1
    if recorder is None:
        print("error: the emulator session could not be started", file=sys.stderr)
        return 1
    if arguments.out:
        write_log(arguments.out, recorder, route, arguments.rom, checks)
    visits = track_visits(recorder.samples, index)
    print(f"route {route['name']}: {recorder.frames} frames, {len(recorder.samples)} distinct samples")
    if checks is not None:
        wrong = [check for check in checks if check["bad_slots"]]
        print(f"marker text read back from the WRAM tile buffers: {len(checks)} runs, {len(wrong)} with a wrong slot {wrong if wrong else ''}".rstrip())
    print(format_report(visits, index))
    return 0


def report_command(arguments: argparse.Namespace) -> int:
    try:
        index = RunIndex(json.loads(arguments.map.read_text(encoding="utf-8")))
        visits: list[Visit] = []
        for log in arguments.log:
            _, samples = read_log(log)
            visits += track_visits(samples, index)
    except (ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if arguments.json:
        print(json.dumps({"summary": summarize(visits, index), "visits": [visit.to_json() for visit in visits]}, indent=1))
    else:
        print(format_report(visits, index))
    return 0


def budgets_command(arguments: argparse.Namespace) -> int:
    try:
        index = RunIndex(json.loads(arguments.map.read_text(encoding="utf-8")))
        visits: list[Visit] = []
        for log in arguments.log:
            visits += track_visits(read_log(log)[1], index)
        text = json.dumps(budgets(visits, index), indent=1, ensure_ascii=False) + "\n"
    except (ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if arguments.out:
        arguments.out.write_text(text, encoding="utf-8", newline="\n")
    else:
        print(text, end="")
    return 0


def walk_command(arguments: argparse.Namespace) -> int:
    text = json.dumps(walk_route(arguments.seed, arguments.moves, arguments.state), indent=1) + "\n"
    if arguments.out:
        arguments.out.write_text(text, encoding="utf-8", newline="\n")
    else:
        print(text, end="")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="ejecuta una ruta en el emulador y escribe el registro")
    run.add_argument("--rom", type=Path, required=True, help="ROM de marcadores")
    run.add_argument("--map", type=Path, required=True, help="mapa JSON de build_marker_rom.py")
    run.add_argument("--route", default="field", help=f"ruta incluida ({', '.join(sorted(ROUTES))})")
    run.add_argument("--route-file", type=Path, help="ruta en un JSON (sustituye a --route)")
    run.add_argument("--savestates", type=Path, help="carpeta de los estados guardados (fuera del repositorio)")
    run.add_argument("--mesen-bin", default=os.environ.get("MESEN_BIN"), help="ejecutable de Mesen (o MESEN_BIN)")
    run.add_argument("--poll", type=int, default=1, help="leer la RAM cada N fotogramas (1: cada uno; más de 2 puede perder tramos)")
    run.add_argument("--out", type=Path, help="registro JSON de las muestras")
    run.add_argument("--check-buffers", action="store_true", help="al dibujarse un marcador, comprobar en la WRAM que sus celdas contienen sus letras")
    report = commands.add_parser("report", help="analiza uno o varios registros sin emulador")
    report.add_argument("--map", type=Path, required=True)
    report.add_argument("--log", type=Path, action="append", required=True)
    report.add_argument("--json", action="store_true", help="resumen y visitas en JSON")
    walk = commands.add_parser("walk", help="escribe una ruta de paseo al azar (JSON) para --route-file")
    walk.add_argument("--seed", type=int, required=True)
    walk.add_argument("--moves", type=int, default=60)
    walk.add_argument("--state", default="field-start.mss")
    walk.add_argument("--out", type=Path)
    limits = commands.add_parser("budgets", help="presupuesto en letras (max) de cada tramo dibujado, a partir de uno o varios registros")
    limits.add_argument("--map", type=Path, required=True)
    limits.add_argument("--log", type=Path, action="append", required=True)
    limits.add_argument("--out", type=Path, help="JSON de salida (por defecto, la salida estándar)")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.command == "run" and arguments.poll < 1:
        print("error: --poll must be at least 1", file=sys.stderr)
        return 2
    commands = {"run": run_command, "report": report_command, "budgets": budgets_command, "walk": walk_command}
    return commands[arguments.command](arguments)


if __name__ == "__main__":
    sys.exit(main())
