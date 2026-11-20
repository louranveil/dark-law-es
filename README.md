# dark-law-es

Spanish fan translation of *Dark Law: Meaning of Death* (Super Famicom, ASCII, 1997), delivered as a BPS patch. The repository holds the tools, text, and documentation needed to build the patch; it never contains a ROM.

## Setup

Enable the repository hooks once per clone:

```sh
git config core.hooksPath .githooks
```

The `pre-commit` hook runs `tools/guard_forbidden_files.py`, which rejects staged ROMs, emulator savestates, and battery saves, by extension and by ROM-like file size. Patches (`.bps`, `.ips`) are allowed.

## Tests

```sh
python -m unittest discover -s tests -v
```
