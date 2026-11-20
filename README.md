# dark-law-es

Traducción al español, hecha por aficionados, de *Dark Law: Meaning of Death* (Super Famicom, ASCII, 1997), que se distribuye como un parche BPS. El repositorio contiene las herramientas, el texto y la documentación necesarios para construir el parche; nunca contiene una ROM.

## Preparación

Activa los hooks del repositorio una sola vez por clon:

```sh
git config core.hooksPath .githooks
```

El hook `pre-commit` ejecuta `tools/guard_forbidden_files.py`, que rechaza ROMs, savestates de emulador y saves de batería en el área de preparación, tanto por extensión como por un tamaño propio de una ROM. Los parches (`.bps`, `.ips`) están permitidos.

## Prueba de humo del emulador

`tools/smoke_emulator.py` comprueba las herramientas de emulador contra la ROM real, desde el reset hasta la pantalla del fotograma 600: que la ROM sea el dump verificado (tamaño y SHA-1 registrados en `docs/re/rom-identity.md`), cabecera y banco de arranque, una captura de 256x224 cuyos colores proceden todos de la CGRAM, estado idéntico en dos sesiones nuevas y una reproducción exacta tras `state.load`. Necesita [mesen-probe](https://github.com/louranveil/mesen-probe) instalado (preferiblemente en un entorno virtual) y las rutas indicadas por argumentos o variables:

```sh
export MESEN_FOR_AI_DIR=/ruta/a/mesen-for-ai/parcheado
export MESEN_BIN=/ruta/a/Mesen
export DARK_LAW_ROM=/ruta/a/la/rom/original
python tools/smoke_emulator.py
```

Tarda unos 30 segundos y termina con 0 si todas las comprobaciones pasan, con 1 si alguna falla y con 2 si el uso o la configuración son incorrectos. Las capturas y el savestate temporal van a un directorio temporal que se borra después, nunca al repositorio (con `--workdir` se pueden conservar en otro sitio). Las mismas comprobaciones se ejecutan como un test que se omite salvo que estén definidas `DARK_LAW_ROM` y las demás variables. La comprobación de colores solo es fiable mientras la paleta es estable, como en la pantalla de título.

## Ingeniería inversa y guiones

Los hallazgos sobre la ROM están en `docs/re/`: [rom-identity.md](docs/re/rom-identity.md) (qué dump se usa), [header.md](docs/re/header.md) (cabecera y conversión de direcciones), [font.md](docs/re/font.md) (fuente de glifos de 16x16) y [text-engine.md](docs/re/text-engine.md) (codificación, comandos, tablas de mensajes, cobertura y puntos abiertos). Cada afirmación está marcada como verificada, respaldada por los datos o suposición.

El estado actual de la primera etapa: los diálogos se almacenan sin comprimir, como flujos de bytes con el texto entre comandos, y se alcanzan por tablas de punteros de 16 bits. Es posible extraerlos y reinsertarlos de forma automática, pero todavía no hay tabla de caracteres ni traducción, y quedan comandos por medir (ver el documento).

Las herramientas son de la biblioteca estándar y reciben la ROM por `--rom` o por `DARK_LAW_ROM`:

```sh
export DARK_LAW_ROM=/ruta/a/la/rom/original
python tools/check_scripts.py                                    # cobertura de blobs y construcción identidad
python tools/build_relocation_probe.py --out /ruta/fuera/del/repositorio/probe.sfc   # prueba de reinserción
```

`tools/script_format.py` implementa el formato (directorio, tablas, tokenizador con la tabla de argumentos de cada comando y su nivel de evidencia), `tools/script_builder.py` las escrituras seguras (registro, bytes esperados de la ROM original, sin solapes) y la reubicación de blobs. `build_relocation_probe.py` alarga el primer mensaje del intro, lo reubica en el relleno del banco `$E2` y repunta la tabla; es solo una prueba para el emulador y su resultado nunca se distribuye.

`tools/probe_command_arity.py` mide con ejecución forzada en el emulador cuántos argumentos consume cada comando del motor de texto (necesita `mesen-probe`, `MESEN_BIN` y un savestate del intro, que no se guarda en el repositorio); sus resultados alimentan la tabla de `script_format.py`.

## Tests

```sh
python -m unittest discover -s tests -v
```

Con `DARK_LAW_ROM` definida, los tests de `tests/test_script_builder.py` que usan la ROM real también se ejecutan; sin ella se omiten.

## Licencia

El código, la documentación y el texto traducido escritos en este repositorio se publican bajo la licencia MIT; consulta [LICENSE](LICENSE). La licencia no cubre el juego: *Dark Law: Meaning of Death* y su texto, gráficos y datos originales pertenecen a sus titulares, y aquí no se distribuye ninguna ROM ni dato del juego, solo parches.
