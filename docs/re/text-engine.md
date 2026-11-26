# Text Engine And Script Format

This file records how the game stores, decodes, and draws its dialogue. Notation follows [header.md](header.md). Each claim is marked **verified** (with how), **measured** (observed in the engine by the forced-execution probe), **read from code** (read in the handler disassembly, not run), **corpus** (supported by patterns in the data, not observed in the engine), or **guess** or **unknown** (with why). Tools that implement this format: `tools/script_format.py`, `tools/check_scripts.py`, `tools/script_builder.py`, `tools/build_relocation_probe.py`.

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

Glyph slots in the narration window (loop 1, window type 1): 24, as two rows of 12 (`$0A45` counts up to `0x18`; slots 0-11 are the first row and 12-23 the second, see [latin-font-spike.md](latin-font-spike.md)); other windows have their own loops and counts, for example 32 slots as two rows of 16 in the field messages, see [window-types.md](window-types.md). The `C3` command sets the slot to 12 in the window type `$0A4C = 1`, so it only works as a line break from the first row.

**Which character each glyph is** is recorded in `tbl/original.json` (920 glyphs, see [glyph-table.md](glyph-table.md)): `0A` is こ, `19` is の, `16` is に, `1A` is は, `FD CB FD 60` is 年前. Four readings are still open.

## Commands

The dispatcher is a state machine: `$D1:0274` jumps through the table at `$D1:0286` on `$0AC4` (the state); state 3 jumps through the table at `$D1:0422` on `$0AC5` (the command minus `$C0`). Handler addresses are in that table (64 entries, `$C0`-`$FF`). The command byte is fetched at `$D1:3B13`; arguments are fetched or skipped by helpers at `$D1:3B37`, `3B61`, `3B7B`, `3B9D`.

Argument counts have four evidence levels, recorded per entry in `tools/script_format.py` (`Evidence.MEASURED`, `CODE`, `CORPUS`, `UNKNOWN`):

- **measured**: a forced-execution probe (`tools/probe_command_arity.py`). The bytes `cmd, 01 02 03 04 05 06, C7 C7 C7 C7` were written to WRAM, the current level of the script pointer stack was pointed at them, the engine ran 8 frames (30 or 300 for commands that wait), and the position where the engine fetched the next command was read with a read watch. When the engine does not return to the dispatcher (a call, a replace, a wait) the next fetch is not visible, and the pointer of the current stack level after the run was used instead: it points at the last argument consumed. The probe was run on the intro savestate with two or more argument patterns, and the patterns agreed for every entry marked measured. It was validated first against commands whose behavior was known from a trace (`C8`=1, `C5`=0, `EE`=2).
- **read from code**: the handler was disassembled and the calls to the argument helpers were counted. The helpers behave as follows: `$D1:3B7B` advances one byte and reads 8 bits; `$D1:3B9D` advances one byte but reads 16 bits; `$D1:3B37` skips one byte and `$D1:3B61` two; `$D1:3B14` and `$D1:3AF6` only peek; `$D1:3AE1` ends the command (advance one more byte, state 0). The length of a command is the total advance from the command byte, counting that final byte. Reading the code does not prove that the engine takes that path with real data, so handlers with conditional paths were followed on every path.
- **corpus**: only the data supports it: the blobs that use the command close exactly at the next blob only with this length.
- **unknown**: nothing supports it; the tokenizer assumes 0 arguments and the extractor flags the entry.

| Command | Arguments | Evidence | Notes |
| --- | --- | --- | --- |
| `C0` | 0 | measured | Starts a message window; text follows. |
| `C1` | 0 | measured | Like `C0`, used after a page break. |
| `C2` | 4 | read from code | Yes/No choice: two 16-bit message ids, and the engine jumps to one of them (a replace: it does not return to this script). Always last: `... 8E C2 0A 00 60 00`, so the blob ends after its arguments. 80 uses. The probe blocks on it. |
| `C3` | 0 | measured | Line break. |
| `C4` | 0 | corpus | Appears after a text run and before `C1`: a page break or wait for a key. Blocks in the probe. |
| `C5` | 0 | measured | Appears between timed waits in the intro. |
| `C6` | 0 | measured | |
| `C7` | 0 | corpus | Ends the blob; 1531 dialogue blobs end with it. |
| `C8` | 1 | measured | Wait `nn` frames (`C8 80` in the intro). |
| `C9`, `CD`-`D4`, `D6`, `D8` | 1 | measured | `D8 nn` calls script `nn` of the table at `$EE:0000` (verified in the handler code). |
| `CA`, `CC` | 0 | measured | |
| `CB`, `DA`, `DB` | 1 | read from code | One 8-bit read each, then the command ends (7 uses of `CB`, 2 of `DB`, none of `DA`). Not measured: the probe blocks after the first argument, which is consistent but proves nothing. |
| `D5`, `DD`, `E3`, `E7`, `F4` | 2 | measured | |
| `D7` | 1 + sub-command | see below | A selector command like `FE`. |
| `D9` | 2 | read from code | Map change: reads two arguments after a screen fade and abandons the script (291 uses, e.g. `D9 00 01 FF`). Previously corpus only. |
| `DC` | 4 | measured | Corpus agrees: `DC 06 00 3D 02`. |
| `DE`-`E2` | 3 | measured | |
| `E4`, `E5`, `E9`, `EA`, `EB`, `EF`, `F6` | 1 | measured | |
| `E6` | 2 | read from code | The handler consumes two argument bytes; not measured (the engine blocks). One use in the data. |
| `E8` | 5 | read from code | A random choice between two messages: a selector byte and two 16-bit message ids, then a replace (the engine continues in the chosen message and never returns), so the blob ends after the fifth argument: `E8 05 3D 00 3A 00`. Earlier notes called its length variable; it is not, the selector changes which id is taken and not how many bytes are read. 9 uses. |
| `EC` | 2 | measured | Map change: two arguments, read after the fade; the script is abandoned. |
| `ED` | 0 | measured | Nearly absent from the data. |
| `EE` | 2 | measured | Calls message `nnnn` (16-bit id): resolves it through the area record (below) and pushes a new level on the pointer stack. |
| `F0` | 0 | corpus | Ends the blob (a one-byte blob `F0` exists). |
| `F1` | 0 | read from code | `F1 FF`: the handler reads no argument and passes to another state (24 uses). |
| `F2` | 5 | measured | |
| `F3` | 2 | read from code | Map change like `D9`: `F3 01 00 FF` (79 uses). |
| `F5` | 0 | measured | |
| `F7`, `F8`, `F9` | n/a | measured | The dispatcher loops on them without consuming bytes: they appear to be invalid and never used (**guess**). |
| `FE` | 1 + sub-command | see below | A selector command. |
| `FF` | 0 | corpus | Ends the blob (scripts and narration). |

A blob ends at the first `C7`, `F0` or `FF` that is read as a command, or at a command after which the engine never reads this script again (a "leaving" command): `C2`, `D9`, `E8`, `EC`, `F3`, and the `FE` sub-commands marked as leaving below. Leaving commands are those whose handler replaces the script pointer with another message (`C2`, `E8`, `FE 40`, `FE 44`, `FE 45`), abandons the script for a map change, or hands the engine over to another routine. The data agrees: a blob can end right after the arguments of a leaving command, without a terminator. Some blobs also carry one or two redundant `C7` or `FF` bytes after their real end (for example `EC 0D 00 FF FF`) that the engine never reads; `tools/script_format.py` accepts up to two of them in the gap (`absorb_dead_tail`).

### FE Sub-commands

The handler of `FE` at `$D1:0C11` reads one byte `v`, stores `v + 0x40` in `$0AC5` and jumps back into the command dispatcher, so each `FE v` is an extended command with its own handler (entries `$40` to `$89` of the table at `$D1:0422`, `v` = `00` to `49`). The length of `FE v` is 2 plus the arguments in the table below (counted after `v`). It does not depend on the argument values: an earlier note said that `FE 08` changed length with the argument values, but that was the probe blocking in a wait state, not a real change. `FE 2D` is the only entry where the code and the data disagree (see its row).

In the data there are 1256 `FE` commands with 45 distinct selectors: 1012 of those uses have a measured length, 243 a length read from code, and 1 a length known only from the corpus.

| Arguments | Selectors (uses in the data, when not zero) | Evidence |
| --- | --- | --- |
| 0 | `0D` (5), `0E` (4), `0F` (1), `10`-`13`, `14` (3), `15` (1): copy a string to the text buffer and run it; `18`, `1A`, `1B`, `1C`, `1F`, `20`, `23`, `25`, `27`, `2F`, `30`, `35`, `36`, `38` (42), `3D`, `3E`, `41` (3), `47` | measured |
| 0 | `26`, `31` (1), `39` (79), `3A` (48), `3B` (1), `49` (1) | read from code |
| 0 | `21`, `46` (2): leaving | read from code |
| 0 | `0A`: pops one level of the pointer stack; no blob uses it | read from code |
| 0 | `34`: the handler enters a wait state (`$2A`) that may read more; no blob uses it | **unknown** |
| 1 | `00` (131), `01` (37), `02`, `07` (57), `0B` (9), `16` (7), `17` (7), `48` (5) | measured |
| 1 | `22` (1): leaving | measured |
| 1 | `24` | read from code |
| 1 | `32` (107): waits and then pops the script level, so it ends the blob (leaving) | read from code |
| 2 | `29` (106), `2A` (20), `2B` (18), `33` (10), `42` (22) | measured |
| 3 | `1D`, `1E` (a conditional jump whose two paths consume the same bytes), `28` (30), `2C` | measured |
| 3 | `0C` (1): map change, leaving | measured |
| 4 | `08` (75), `43` (4) | measured |
| 5 | `09` (100) | measured |
| 6 | `03` (89), `04` (59), `19` (73), `2E` (11), `3C`, `3F` (66) | measured |
| 6 | `37` (1) | read from code |
| 6 | `2D` (1) | **corpus**: with the group member present the engine consumed 7 bytes in the probe (3 without it), but the only blob that uses it closes exactly with 6 |
| 7 | `05` (2), `06` (1) | measured |
| 8 | `40`, `44`, `45` (1 each): jump to one of four 16-bit message ids (leaving) | read from code |

Selectors from `4A` up have no handler in the table. Only `FE F4` appears in the data (12 times, always followed by two bytes, as in `FE F4 FE 02`); the probe showed that the engine runs it as `F4` with its two arguments, so it is recorded with 2 arguments, measured. Any other selector is **unknown** and flagged.

### D7 Sub-commands

`D7` reads a selector `s` (its handler at `$D1:06B0` dispatches through the 157-entry table at `$D1:4EF1`). Most selectors read no argument after `s`. Read from the handlers (not measured): `D7 19` has 5 (125 uses; the blobs close exactly with that), `D7 48` has 2, `D7 6A` has 6, and `D7 6B`, `D7 8C` and `D7 92` have 1. Seventeen selectors (`24`, `28`, `3E`, `3F`, `44`-`47`, `4E`-`54`, `5D`, `76`) go through a second table or several phases and their handlers were not followed completely: they are recorded with 0 arguments as **corpus** evidence (16 uses, and every blob that uses them closes exactly). The probe was also tried on `D7 00`-`18`, but every case ended in the same state without evidence of reaching the handler; the cause was not investigated, so nothing about `D7` is measured. 21 of the 157 selectors never appear in the data.

The arity table lives in `tools/script_format.py` with each entry's evidence level. `tokenize` reports in `unresolved` the commands it met whose length is not measured (the key is the command, or the command followed by the selector for `FE` and `D7`, for example `0xFE40`), and the extractor flags an entry only when one of those has **unknown** evidence.

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
- Blobs are contiguous: the byte before the start of the next blob is the last byte (a terminator) of the previous one in the great majority of cases. 2794 of 2797 blobs close exactly (it was 2598 before the argument counts of `FE`, `E8` and the others were resolved). The remaining 3 are listed in Coverage.
- Besides the area tables, a second table of 112 pointers at `$EE:0000` holds scripts called by command `D8` (99 distinct blobs, 404 glyph bytes). It is included in the tools.
- The nine words before `T0` of area 8 (`$E2:EE61`-`$E2:EE72`, values `F50F F5A2 F5CF ...`) were not explained.
- Nested calls: the script pointer stack is in WRAM, depth at `$0A8D`, 3 bytes per level from `$0A8F`. In the intro, level 0 is the event script (`$E2:F3D3`, `F401`...), and the `EE` command pushes level 1 with the message blob.

Which code builds a message pointer from an immediate or a base plus index, other than `$D1:3A54` and the `D8` handler, was **not** searched exhaustively. A scan for code that touches `$0A8D`/`$0A8F` found writers at `$D1:06E3`, `09C9`, `3ACE`, `3B75`, `3B8E`, `3BB0`, `45A3`, `4799`, `4991`, `4AC9`, `4C8D`; only the first three were read.

## Coverage

Run `tools/check_scripts.py` against the verified dump. A blob closes exactly when its tokens end in a terminator or a leaving command, followed by at most two redundant `C7` or `FF` bytes, exactly where the next blob of the same table starts (for the last blob of a table the only requirement is the terminator):

| Table role | Blobs closing exactly | Needing review |
| --- | --- | --- |
| Messages (`T0`, ids `< 0x200`) | 1653 | 1 |
| Event scripts (`T1`) | 908 | 1 |
| Global (`T2`) | 135 | 0 |
| Called scripts (`$EE:0000`) | 98 | 1 |

2794 of 2797 blobs close exactly (2598 before the sub-command lengths were resolved), and the identity build is byte-identical to the original ROM. The three that do not close:

- `$EC:0478` (messages): ends in `E6 1B 00 13 00 14 00`, glyphs included, without a terminator before the next blob. `E6` has 2 arguments by the code, so either `E6` reads more in this case or the blob continues in the next one. **Unresolved.**
- `$EE:0BF7` (called scripts): the 12-byte blob ends with `EE 22 00` and has no terminator, so it probably falls through into the next blob. **Unresolved.**
- `$EE:525D` (events): terminates after 31 bytes, and 4948 more bytes follow before the next blob start; probably data that nothing points at. **Unresolved.**

Dialogue is concentrated in `T0`: 76068 bytes of glyph codes in the exact blobs. The event, global and called scripts hold much less (431, 2795 and 0 glyph bytes). Most of what earlier counts took for text there was the arguments of `FE` and `E8`; what remains in those tables was not reviewed as text.

Text that does **not** go through these scripts was not analyzed: the title menu (`最初からはじめる`), item and spell names, status screens, battle messages, and anything else drawn by another path. Whether they use the same font routine or their own is unknown.

## Free Space

Status: **guess** except where stated.

Every bank from `$E2` to `$EE` ends in `0xFF` filler, for example `$E2:F8A6`-`$E2:FFFF` (`0x75A` bytes) and `$D2:BB78`-`$D2:FFFF` (`0x4488` bytes) between two font pages. A scan lists 38 runs of `0xFF` of 2 KiB or more over the whole ROM. Having seen nothing but `0xFF` in a ROM image does not prove that the game never reads or expects those bytes.

The range `$E2:F8A6`-`$E2:FFFF` was used by the relocation probe below: the intro ran from reset through the relocated message without any visible problem, which proves only that this route does not read it.

## Relocation Probe

Status: **verified**.

`tools/build_relocation_probe.py` takes message 0 of the table at `$E2:EE73` (the intro's `300年前・・・`, 79 bytes), inserts three `・` glyphs (`9E`) before its first `C8`, writes the 82-byte blob at `$E2:F8A6` and updates the 16-bit pointer at `$E2:EE73`. Only those two ranges differ from the original (checked by `tests/test_script_builder.py`).

Booted from reset in MesenCE and driven with the same inputs (Start at the title, A at the menu), the original ROM shows `300年前・・・` in four captures between frames 1460 and 1620, and the probe ROM shows `300年前・・・・・・` with the sixth dot wrapped to the second row in the same four captures. In a separate run of the same route, after the first message the two ROMs reached identical screens at three later captures (about frames 1948, 2248, and 2548). This proves that the engine reads a blob from another place through the repointed table and that a longer text is accepted; it also shows that the narration window wraps on its own after 12 glyph slots (the blob starts with two blank glyphs and `300年前` plus six dots makes 13, so the thirteenth, the sixth dot, goes to the second row). An earlier version of this file said 11 per line; the draw tables in [latin-font-spike.md](latin-font-spike.md) show 12.

## Extraction

Status: **verified** by round trip, with the limits listed here. `tools/extract_script.py` turns every blob into an entry made of a skeleton (the commands, never edited) and text runs (what gets translated), see the header of the tool for the format.

- 2797 distinct blobs; 2794 close exactly and have no doubtful command (2429 before the argument counts were resolved); 1691 hold text (4993 runs), 1689 of them without doubt. Before, 1874 entries held "text" (5523 runs) and 350 of them were flagged.
- By role, with the text entries that have no doubt: messages 1548 of 1549 (4729 of 4731 runs), event scripts 18 of 19, global table 123 of 123, called scripts none. The text of the event and global tables was not reviewed.
- The 3 entries flagged for review are the 3 blobs that do not close (see Coverage); two of them hold text. The extractor no longer flags a run that comes right after an `FE` or `E8` (it did while their lengths were unknown). It flags an entry only when it uses a command whose length is **unknown**: an `FE` selector of `34`, or from `4A` up other than `F4`, or a `D7` selector outside its table. None occurs in the ROM.
- Round trip: every entry rebuilds its bytes from the skeleton and the `raw` of its runs, and the readable `jp` of every run parses back to `raw`, for the whole ROM.
- The dumped files (`text/`) hold the original Japanese text and are not committed.

## Open Items

1. Glyph table: done for the 920 glyphs in use, see [glyph-table.md](glyph-table.md); four readings and the second reader are open.
2. Argument counts: resolved for every command that appears in the ROM, with the evidence level of each entry in the Commands section. Still open: measure what is only read from code (in particular `C2`, `D9`, `E8`, `EC`, `F3`, the `FE` leaving selectors, and all of `D7`); decide `FE 2D` (code says 7 arguments with the group member present, the data says 6); follow the multi-phase `D7` handlers (17 selectors); determine `FE 34`; and explain the three blobs that do not close (`$EC:0478`, `$EE:0BF7`, `$EE:525D`).
3. Find every reader of the pointer tables (code that builds addresses from immediates), and confirm that no code reads a blob by absolute address, before moving blobs for real.
4. Verify free space with trap bytes across a long route; until then use only the ranges needed.
5. Analyze the paths that draw other text (menus, items, battle, names).
6. Spanish font path: a fixed-width proof of concept works, see [latin-font-spike.md](latin-font-spike.md). Still open: a proportional-width path, measuring the other window types, and a real font.
7. The forced-execution probe is `tools/probe_command_arity.py` and needs a savestate taken at the intro (the workspace `savestates/intro-300-years.mss` was used). The route from reset to the intro (620 frames, Start for 4 frames, 300 frames, A for 4 frames, 10 frames) and the read-watch traces used for this document were run from throwaway scripts and are not in the repository yet.
