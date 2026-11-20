# dark-law-es

Spanish fan translation of *Dark Law: Meaning of Death* (Super Famicom, ASCII, 1997), delivered as a BPS patch. The repository holds the tools, text, and documentation needed to build the patch; it never contains a ROM.

## Setup

Enable the repository hooks once per clone:

```sh
git config core.hooksPath .githooks
```

The `pre-commit` hook runs `tools/guard_forbidden_files.py`, which rejects staged ROMs, emulator savestates, and battery saves, by extension and by ROM-like file size. Patches (`.bps`, `.ips`) are allowed.

## Emulator smoke test

`tools/smoke_emulator.py` checks the emulator tooling against the real ROM, from reset to the screen at frame 600: header and boot bank, a 256x224 capture whose colors all come from CGRAM, identical state in two fresh sessions, and an exact replay after `state.load`. It pins no hash derived from the ROM. It needs the generic tools installed in the workspace virtual environment (see `tools/README.md` in the workspace) and the paths given by arguments or variables:

```sh
export MESEN_FOR_AI_DIR=/path/to/patched/mesen-for-ai
export MESEN_BIN=/path/to/Mesen
export DARK_LAW_ROM=/path/to/the/original/rom
python tools/smoke_emulator.py
```

It takes about 30 seconds and exits with 0 when every check passes, 1 when one fails, and 2 for wrong usage or configuration. Captures and the temporary savestate go to a temporary directory that is deleted afterwards, never into the repository (use `--workdir` to keep them elsewhere). The same checks run as a test that is skipped unless `DARK_LAW_ROM` and the other variables are set. The color check is only reliable while the palette is stable, as on the title screen.

## Tests

```sh
python -m unittest discover -s tests -v
```

## License

The code, documentation, and translated text written in this repository are released under the MIT License; see [LICENSE](LICENSE). The license does not cover the game: *Dark Law: Meaning of Death* and its original text, graphics, and data belong to their rights holders, and no ROM or game data is distributed here, only patches.
