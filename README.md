# dark-law-es

Traducción al español, hecha por aficionados, de *Dark Law: Meaning of Death* (Super Famicom, ASCII, 1997), que se distribuye como un parche BPS. El repositorio contiene las herramientas, el texto y la documentación necesarios para construir el parche; nunca contiene una ROM.

## Preparación

Activa los hooks del repositorio una sola vez por clon:

```sh
git config core.hooksPath .githooks
```

El hook `pre-commit` ejecuta `tools/guard_forbidden_files.py`, que rechaza ROMs, savestates de emulador y saves de batería en el área de preparación, tanto por extensión como por un tamaño propio de una ROM. Los parches (`.bps`, `.ips`) están permitidos.

## Licencia

El código, la documentación y el texto traducido escritos en este repositorio se publican bajo la licencia MIT; consulta [LICENSE](LICENSE). La licencia no cubre el juego: *Dark Law: Meaning of Death* y su texto, gráficos y datos originales pertenecen a sus titulares, y aquí no se distribuye ninguna ROM ni dato del juego, solo parches.
