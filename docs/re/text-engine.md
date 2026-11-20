# Text Engine And Script Format

This file records how the game stores, decodes, and draws its dialogue. Notation follows [header.md](header.md). Each claim is marked **verified** (with how), **corpus** (supported by patterns in the data, not observed in the engine), or **guess** (with why). Tools that implement this format: `tools/script_format.py`, `tools/check_scripts.py`, `tools/script_builder.py`, `tools/build_relocation_probe.py`.

## Verdict

Status: **verified** by an extraction and reinsertion round trip, see the last section.

- No compression was found in the text or in the font: both are plain bytes that decode as they are.
- The dialogue is stored as byte streams ("blobs") with the text inline between control codes. Blobs are reached through 16-bit pointer tables. This is a good case for automation: 1628 of 1654 dialogue blobs tokenize exactly up to the start of the next blob, and a byte-identical identity build passes.
- The font has 16x16 glyphs only, drawn one glyph per 4 tiles. A Spanish translation will need a new, narrower glyph path in the engine, not only new text. That is a code change, not a text change, and it is the main risk of the project (see Open Items).
- The command argument counts are only partly measured; some commands still need work before every blob can be trusted.

## Text Encoding

Status: **verified** (the engine code at `$D1:4553`-`$D1:46A6` was read, and the read order was traced in MesenCE with read watches on a script block).

The text interpreter reads bytes through a long pointer in direct page `$1D`-`$1F` (`LDA [$1D],Y` at `$D1:4571`). A byte `b` means:

| Byte | Meaning |
| --- | --- |
| `00`-`BF` | One glyph of the single-byte page (spaces, kana, digits, punctuation). `00` is a blank glyph. |
| `FA xx`, `FB xx`, `FC xx`, `FD xx` | One glyph of a kanji page: the prefix selects the page (`FD` page 0 ... `FA` page 3), `xx` is the glyph in the page. See [font.md](font.md). `xx` can be any value, including `C0`-`FF`. |
| `C0`-`F9`, `FE`, `FF` | A command. The text routine stops at the first command that it does not handle itself and hands the byte to the command dispatcher. |
| `C3` | Line break inside text (handled by the text routine itself). |
| `E5 nn` | Skips `nn` glyph slots (handled by the text routine itself). |

Characters per window: 24 glyph slots (`$0A45` counts up to `0x18`).

**Which character each glyph is has not been decided yet.** The glyph indices are known and stable; the mapping to Unicode needs a table. A first attempt with template matching against MS Gothic gave scores of 0.6-0.8 without a clear winner (for example it confused `は` with `ぱ`), so the table needs human review. From the intro: `0A` is こ, `19` is の, `16` is に, `1A` is は, `FD CB FD 60` is 年前.

## Commands

The dispatcher is a state machine: `$D1:0274` jumps through the table at `$D1:0286` on `$0AC4` (the state); state 3 jumps through the table at `$D1:0422` on `$0AC5` (the command minus `$C0`). Handler addresses are in that table (64 entries, `$C0`-`$FF`). The command byte is fetched at `$D1:3B13`; arguments are fetched or skipped by helpers at `$D1:3B37`, `3B61`, `3B7B`, `3B9D`.

Argument counts were measured with a forced-execution probe: the byte `cmd, 01 02 03 04 05 06, C7 C7 C7 C7` was written to WRAM, the current level of the script pointer stack was pointed at it, the engine ran 8 frames, and the position where the engine fetched the next command was read with a read watch. The probe was run on the intro savestate state, with two argument patterns (`01..06` and `00..00`), and both patterns agreed for every command. The probe validated first against commands whose behavior was already known from a trace (`C8`=1, `C5`=0, `EE`=2).

| Command | Arguments | Evidence | Notes |
| --- | --- | --- | --- |
| `C0` | 0 | measured | Starts a message window; text follows. |
| `C1` | 0 | measured | Like `C0`, used after a page break. |
| `C2` | 4 | corpus | Ends the blob. Always last: `... 8E C2 0A 00 60 00`. The engine blocks on it, so the probe could not measure it. |
| `C3` | 0 | measured | Line break. |
| `C4` | 0 | corpus | Appears after a text run and before `C1`: a page break or wait for a key. Blocks in the probe. |
| `C5` | 0 | measured | Appears between timed waits in the intro. |
| `C6` | 0 | measured | |
| `C7` | 0 | corpus | Ends the blob; 1531 dialogue blobs end with it. |
| `C8` | 1 | measured | Wait `nn` frames (`C8 80` in the intro). |
| `C9`, `CD`-`D4`, `D6`, `D7`, `D8` | 1 | measured | `D8 nn` calls script `nn` of the table at `$EE:0000` (verified in the handler code). |
| `CA`, `CC` | 0 | measured | |
| `CB`, `DA`, `DB` | 1 | **guess** | The engine blocked after reading the first argument; the real count may be higher. |
| `D5`, `DD`, `E3`, `E7`, `F4` | 2 | measured | |
| `D9` | 2 | corpus | `D9 00 01 FF`; blocks in the probe. |
| `DC` | 4 | measured | Corpus agrees: `DC 06 00 3D 02`. |
| `DE`-`E2` | 3 | measured | |
| `E4`, `E5`, `E9`, `EA`, `EB`, `EF`, `F6` | 1 | measured | |
| `E6` | 2 | **guess** | Blocks; rare. |
| `E8` | variable | **unknown** | Reads one argument, then more depending on its value. Appears at the end of blobs: `E8 05 3D 00 3A 00`. |
| `EC`, `ED` | 0 | **guess** | `ED` is nearly absent from the data. |
| `EE` | 2 | measured | Calls message `nnnn` (16-bit id): resolves it through the area record (below) and pushes a new level on the pointer stack. |
| `F0` | 0 | corpus | Ends the blob (a one-byte blob `F0` exists). |
| `F1` | 0 | corpus | `F1 FF`. |
| `F2` | 5 | measured | |
| `F3` | 2 | corpus | `F3 01 00 FF`. |
| `F5` | 0 | measured | |
| `F7`, `F8`, `F9` | n/a | measured | The dispatcher loops on them without consuming bytes: they appear to be invalid and never used (**guess**). |
| `FE` | variable | **unknown** | Two arguments in the probe, but `FE 14 FF` appears as a complete blob in the global table, so the length depends on the first argument (a sub-command). |
| `FF` | 0 | corpus | Ends the blob (scripts and narration). |

A blob ends at the first `C2` (after its 4 arguments), `C7`, `F0`, or `FF` that is read as a command.

The arity table lives in `tools/script_format.py` with each entry's evidence level; `tokenize` reports the commands it met whose count is not measured, and the check marks those blobs for review.

## Message Database

Status: **verified** for the lookup (code at `$D1:3A54`, and the pointer stack traced in MesenCE through the new-game intro), **verified** for the tables (read from the ROM and checked by tokenizing every blob).

```
$EF:0000  directory: 32 areas x 3-byte long pointer to the area record (only the first 16 are real; the rest point to $E5:0000)
area record (9 bytes): three long pointers T0, T1, T2
T0  tables of 16-bit pointers, ids 0x000-0x1FF   dialogue messages
T1  tables of 16-bit pointers, ids 0x200-0x3FF   event scripts of the area
T2  tables of 16-bit pointers, ids >= 0x400      one table ($EF:C1FB) shared by all areas
```

- The variables are: `$0A3E` pointer to the current area index byte (`$09C7`), `$0A42`-`$0A44` the directory pointer (`$EF:0000`), `$0AC1` the message id. In the new-game intro the area index is 8 and its record is at `$E2:EE58`, with `T0 = $E2:EE73` (16 entries), `T1 = $E2:F393` (32 entries), `T2 = $EF:C1FB` (192 entries).
- A table entry is a 16-bit address in the bank of the table. A table ends where its first blob starts: the blobs follow the table immediately. This holds for all 25 tables, but it is a property of the original ROM: after moving a blob the length of the table must come from the original extraction, not be rediscovered.
- Entries can repeat (`$F392` appears four times in `T0` of area 8): several ids share the same blob, here the one-byte blob `FF`.
- Blobs are contiguous: the byte before the start of the next blob is the last byte (a terminator) of the previous one in the great majority of cases. 2598 of 2797 blobs close exactly. The remaining 199 are listed by `tools/check_scripts.py` (131 without a terminator before the next blob, mostly the variable-length `FE` and `E8`; 68 with unexplained gaps before the next blob). Nothing was assumed about them.
- Besides the area tables, a second table of 112 pointers at `$EE:0000` holds scripts called by command `D8` (99 distinct blobs, 404 glyph bytes). It is included in the tools.
- The nine words before `T0` of area 8 (`$E2:EE61`-`$E2:EE72`, values `F50F F5A2 F5CF ...`) were not explained.
- Nested calls: the script pointer stack is in WRAM, depth at `$0A8D`, 3 bytes per level from `$0A8F`. In the intro, level 0 is the event script (`$E2:F3D3`, `F401`...), and the `EE` command pushes level 1 with the message blob.

Which code builds a message pointer from an immediate or a base plus index, other than `$D1:3A54` and the `D8` handler, was **not** searched exhaustively. A scan for code that touches `$0A8D`/`$0A8F` found writers at `$D1:06E3`, `09C9`, `3ACE`, `3B75`, `3B8E`, `3BB0`, `45A3`, `4799`, `4991`, `4AC9`, `4C8D`; only the first three were read.

## Coverage

Run `tools/check_scripts.py` against the verified dump:

| Table role | Blobs closing exactly | Needing review |
| --- | --- | --- |
| Messages (`T0`, ids `< 0x200`) | 1628 | 26 |
| Event scripts (`T1`) | 869 | 40 |
| Global (`T2`) | 17 | 118 |
| Called scripts (`$EE:0000`) | 84 | 15 |

Dialogue is concentrated in `T0`: 75018 bytes of glyph codes in the exact blobs. `T1` and `T2` hold almost no text (1461 and 290 glyph bytes), mostly commands. Most of the 118 global-table failures are blobs made only of `FE` commands.

Text that does **not** go through these scripts was not analyzed: the title menu (`最初からはじめる`), item and spell names, status screens, battle messages, and anything else drawn by another path. Whether they use the same font routine or their own is unknown.

## Free Space

Status: **guess** except where stated.

Every bank from `$E2` to `$EE` ends in `0xFF` filler, for example `$E2:F8A6`-`$E2:FFFF` (`0x75A` bytes) and `$D2:BB78`-`$D2:FFFF` (`0x4488` bytes) between two font pages. A scan lists 38 runs of `0xFF` of 2 KiB or more over the whole ROM. Having seen nothing but `0xFF` in a ROM image does not prove that the game never reads or expects those bytes.

The range `$E2:F8A6`-`$E2:FFFF` was used by the relocation probe below: the intro ran from reset through the relocated message without any visible problem, which proves only that this route does not read it.

## Relocation Probe

Status: **verified**.

`tools/build_relocation_probe.py` takes message 0 of the table at `$E2:EE73` (the intro's `300年前・・・`, 79 bytes), inserts three `・` glyphs (`9E`) before its first `C8`, writes the 82-byte blob at `$E2:F8A6` and updates the 16-bit pointer at `$E2:EE73`. Only those two ranges differ from the original (checked by `tests/test_script_builder.py`).

Booted from reset in MesenCE and driven with the same inputs (Start at the title, A at the menu), the original ROM shows `300年前・・・` in four captures between frames 1460 and 1620, and the probe ROM shows `300年前・・・・・・` with the sixth dot wrapped to the second row in the same four captures. In a separate run of the same route, after the first message the two ROMs reached identical screens at three later captures (about frames 1948, 2248, and 2548). This proves that the engine reads a blob from another place through the repointed table and that a longer text is accepted; it also shows that the line holds 11 glyphs and wraps on its own.

## Open Items

1. Map glyph indices to characters (table, human review).
2. Measure the real argument counts of `CB`, `DA`, `DB`, `E6`, `E8`, `EC`, `ED`, and the sub-command lengths of `E8` and `FE`, then re-run the check. The remaining 199 blobs need this.
3. Find every reader of the pointer tables (code that builds addresses from immediates), and confirm that no code reads a blob by absolute address, before moving blobs for real.
4. Verify free space with trap bytes across a long route; until then use only the ranges needed.
5. Analyze the paths that draw other text (menus, items, battle, names).
6. Design the Spanish font path: variable-width or half-width glyphs, line width budgets per window type (measured), and the change to the draw routine at `$D1:4630`-`$D1:46A3`, which assumes 2 tiles per glyph and 24 slots.
7. The forced-execution probe is `tools/probe_command_arity.py` and needs a savestate taken at the intro (the workspace `savestates/intro-300-years.mss` was used). The route from reset to the intro (620 frames, Start for 4 frames, 300 frames, A for 4 frames, 10 frames) and the read-watch traces used for this document were run from throwaway scripts and are not in the repository yet.
