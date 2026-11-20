# dark-law-es

Traducción al español, hecha por aficionados, de *Dark Law: Meaning of Death* (Super Famicom, ASCII, 1997), que se distribuye como un parche BPS. El repositorio contiene las herramientas, el texto y la documentación necesarios para construir el parche; nunca contiene una ROM.

## Preparación

Activa los hooks del repositorio una sola vez por clon:

```sh
git config core.hooksPath .githooks
```

El hook `pre-commit` ejecuta `tools/guard_forbidden_files.py`, que rechaza ROMs, savestates de emulador y saves de batería en el área de preparación, tanto por extensión como por un tamaño propio de una ROM. Los parches (`.bps`, `.ips`) están permitidos.

## Prueba de humo del emulador

`tools/smoke_emulator.py` comprueba las herramientas de emulador contra la ROM real, desde el reset hasta la pantalla del fotograma 600: cabecera y banco de arranque, una captura de 256x224 cuyos colores proceden todos de la CGRAM, estado idéntico en dos sesiones nuevas y una reproducción exacta tras `state.load`. No fija ningún hash derivado de la ROM. Necesita [mesen-probe](https://github.com/louranveil/mesen-probe) instalado (preferiblemente en un entorno virtual) y las rutas indicadas por argumentos o variables:

```sh
export MESEN_FOR_AI_DIR=/ruta/a/mesen-for-ai/parcheado
export MESEN_BIN=/ruta/a/Mesen
export DARK_LAW_ROM=/ruta/a/la/rom/original
python tools/smoke_emulator.py
```

Tarda unos 30 segundos y termina con 0 si todas las comprobaciones pasan, con 1 si alguna falla y con 2 si el uso o la configuración son incorrectos. Las capturas y el savestate temporal van a un directorio temporal que se borra después, nunca al repositorio (con `--workdir` se pueden conservar en otro sitio). Las mismas comprobaciones se ejecutan como un test que se omite salvo que estén definidas `DARK_LAW_ROM` y las demás variables. La comprobación de colores solo es fiable mientras la paleta es estable, como en la pantalla de título.

## Tests

```sh
python -m unittest discover -s tests -v
```

## Licencia

El código, la documentación y el texto traducido escritos en este repositorio se publican bajo la licencia MIT; consulta [LICENSE](LICENSE). La licencia no cubre el juego: *Dark Law: Meaning of Death* y su texto, gráficos y datos originales pertenecen a sus titulares, y aquí no se distribuye ninguna ROM ni dato del juego, solo parches.
