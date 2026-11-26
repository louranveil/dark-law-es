# Message Tour

Stage 3 of [../specs/translation-pipeline.md](../specs/translation-pipeline.md): a ROM where every text run is a readable marker, and a tour of the game that records, from RAM and not from the screen, which window type each message is drawn in. Notation follows [text-engine.md](text-engine.md): **verified** (observed in the emulator), **measured** (counted from the ROM or the logs), **corpus** (a pattern in the data), **guess** (with why). Tools: `tools/build_marker_rom.py` and `tools/tour_messages.py`, with tests in `tests/test_build_marker_rom.py` and `tests/test_tour_messages.py`.

## Verdict

Status: the method is **verified** and the slice is measured; the tour of the whole game is **not done**.

- The marker build works for the whole script, not only for the slice: with `--all` it marks every text run of every message entry that the extractor calls `ok` (4729 runs in 1548 entries), in place, with nothing relocated.
- The tour reaches 43 of the 350 runs of the slice: the whole intro table (12 entries, 41 runs, from a cold boot) and 2 of the 309 field runs. Window type 1 was measured in 41 runs of the intro and window type 2 in 2 runs of the field. Everything else is unreached and listed by the tool.
- The slot limit of each window was measured with a ruler: 24 slots (48 letters) per page in type 1 and 32 slots (64 letters) in type 2. The row model behind the budgets (`C3` starts the second row at slot 12 in type 1 and 16 in type 2) predicted the counter of 43 of 43 runs of the original game.
- The opening command of a page fixes its window type: `C0` gives type 1 and `C1` gives type 2. This is read from the code and agrees with every run drawn. It lets the budget of the runs the tour did not reach be predicted, marked as a prediction.

## Marker Build

`tools/build_marker_rom.py` takes the original ROM, the glyph table and the extracted entries (`extract_script.build_entries`, only status `ok`, only the `messages` role) and writes a ROM and a JSON map. Every text run becomes a marker written with the Latin pair token `F9 a b` ([latin-font-spike.md](latin-font-spike.md)) and the project font; the skeleton, meaning every command, is copied as it is and checked against the original blob (the command sequence must be the same and the blob must close).

- **Marker text.** The marker of run `n` of blob `E2:EE93` is `E2EE93.n` (8 letters, 12 bytes). A run that is too short for it gets `EE93.n`, `93.n` or `#n` (2 letters, 3 bytes); a run shorter than 3 bytes keeps its original text and is reported. The marker is never longer than the text it replaces, and the map names every run exactly, so a short marker costs no information.
- **In place.** Because a marker never exceeds its run, a blob never grows. It is written where it was, with `FF` after its terminator, and no pointer changes. Nothing is relocated and no free space is used. The relocation of the pipeline ([../specs/translation-pipeline.md](../specs/translation-pipeline.md#placement-and-capacity)) is not exercised by the marker build, only by the rulers below and by the earlier relocation probe ([text-engine.md](text-engine.md#relocation-probe)).
- **Rulers.** `--ruler ID` fills every run of that entry with the marker followed by digits up to 80 letters (40 slots, more than any window holds), to measure how many slots a window accepts. The blob grows, so it is relocated into `$E2:F8A6`-`$E2:FFFF` or `$E7:FC81`-`$E7:FFFF`, the two ranges that earlier spikes used (re-checked to be all `0xFF` at each build, which proves only what text-engine.md says it proves) and every pointer slot of the entry is repointed. The tool fails with the entry id if a ruler does not fit (tested with 4000 letters) or if the bank has no verified range.
- **Write log.** Every write goes through `RomPatcher`. After asar installs the hook and the font (the same `asm/latin_pair_hook.asm`, regions `$D1:4587`, `$D1:477D`, `$D2:BB80`-`$D2:FFFF`), every changed byte must lie in the log or in those regions, or the build fails naming the offset. The ROM and its map are written outside the repository and the tool refuses a path inside it.
- **Map.** One JSON per build: for every entry the original and new address, the slots that point to it and the skeleton; for every run its first and last address in the new blob, its marker, the rows of the original text and, for a ruler, the letters written. The tour reads it; `--map-only` writes the same map for the original ROM so that the tour can run on the untouched game.

Measured with the extractor as it stood on 2026-11-25 (the counts move when the extractor learns more commands, because more entries become `ok`):

| Build | Entries | Runs | Marked | Full marker (8 letters or more) | Left as they were | Blob bytes before and after |
| --- | --- | --- | --- | --- | --- | --- |
| Slice (`$E2:EE73` intro and `$E7:362B` field tables) | 126 | 350 | 350 | 252 | 0 | 7451 to 5126 |
| Everything (`--all`) | 1548 | 4729 | 4634 | 3363 | 95 | 98073 to 65883 |

The build takes about two seconds. The runs left as they were are the ones of one or two narrow glyphs. The entries that the extractor calls `review` (runs after `FE` or `E8`) are not touched. Only the slice was driven in the emulator; the full ROM was loaded and drew its markers in the field route (an earlier extractor state), nothing more was run on it.

## Tour

`tools/tour_messages.py run` drives MesenCE with a route, reads WRAM after every poll and writes a log. `report` analyses logs without the emulator (several logs can be merged), `budgets` writes the budget of every run and `walk` writes a random-walk route.

**Route as data.** A route is a JSON object (or an entry of `ROUTES` in the tool): a start (`{"state": "<file in the savestates directory>"}` or `{"reset": <frames>}` for a cold boot) and steps, each one `{"wait": n}` or `{"press": [buttons], "hold": n, "release": n, "times": n}`. It is validated before it runs. The built-in routes are `field` (from `field-start.mss`, 18 steps down and 16 left, then A), `intro` (from `intro-300-years.mss`, A every 60 frames) and `intro-cold` (reset, 600 frames, Start, A, then A every 60 frames for 300 presses).

**What is read.** After each poll the tool reads `$0A3C`-`$0ACF` and `$1D`-`$1F` with `cpu.read_memory` on `snesWorkRam`: the window type `$0A4C`, the slot counters `$0A45`, `$0A47`, `$0A49`, the message id `$0AC1`, the script pointer stack depth `$0A8D`, the pointer of the top level (3 bytes per level from `$0A8F`) and the command state `$0AC4`/`$0AC5`. Samples are logged when they change. The savestates and the ROM are inputs; nothing is written inside the repository.

**How a run is recognized (verified).** The text routine reads the glyphs through `$1D`-`$1F` but keeps the position of the script in the stack, and writes it back only when it reaches a command it does not handle itself (`$D1:459E`-`$D1:45A3`). So the top of the stack points at the first byte of the run while the run is drawn and at the command that follows it once it is drawn, and both addresses belong to that run alone. The frame-by-frame log of the original game in the field shows it: at frame 430 message id 3 is called with the pointer at the start of its blob; at frame 432 the window type is 2, the counter `$0A47` is 13 and the pointer is at the end of the first run (`$E7:37AE`); two frames later the pointer is past the next command (`C4`, waiting for a key); at frame 750, after A, the counter is 26 and the pointer is at the end of the second run (`$E7:37CD`). The counter is read in the sample in which the pointer is at the end of a run (the draw is done in one frame) and not before, because before it still holds the previous page. `$1D`-`$1F` is **not** a reliable copy of the script pointer outside the text loop: in the field it held `$F9:0000`, so the stack is used. text-engine.md calls it the active script pointer, which is true only inside the loops.

**Poll interval (verified).** The pointer stays at the end of a run for a few frames (the dispatcher takes one command per frame or two). With `--poll 4` a run that is followed at once by commands was missed (`$E7:379B` run 1 in the field; in the intro the poll-4 run of the original ROM saw 23 runs where the poll-2 run saw 27 with the same map). Use 1 or 2: a run reported as unreached with a larger poll may be a sampling miss.

**Runs on the untouched game (verified).** The same routes run on the original ROM with the map of `--map-only`. The window type and message id of each run are the same as in the marker ROM, and the draw frames are the same in the field (432 and 749) and within 4 frames in the cold intro (poll of 2 frames; the intro waits on timers and presses). So the marker ROM does not change which window opens; it changes only what is drawn. The original-ROM tour is also what measures the row model below.

**Text read back from RAM (verified).** With `--check-buffers`, when a marker run is drawn the tool reads the tile buffer of each slot from WRAM (the buffer address table of the loop, `$D1:46DB` or `$D1:48B3`, 32 bytes at the buffer and 32 at `+0x100`) and compares it with the two font letters of the marker. The check passed for 6 marker runs of the first build (2 in type 2 in the field, 4 in type 1 in the intro) and for 36 of 37 runs of the cold intro. The 37th (`$E2:F36F` run 1) was reported as wrong because the first version of the check assumed that the marker starts at slot 0, while that run follows another run on the same page (the counter was 5 for a 4-slot marker). The check now starts at the counter minus the marker length. That fix is covered by unit tests but the 18000-frame route was not run again in the emulator, so for that one run the evidence is only a guess that fits the counter. Ruler runs are not checked. So the markers do show their ids and no screenshot was needed.

**Sessions.** MesenCE sessions started at the same moment can fail with `WinError 10048` (the local bridge port is chosen and then used by another session). The tool retries three times; start one session at a time for long runs.

## Measurements

All of it was run on 2026-11-25 with the savestates of the workspace (`field-start`, `intro-300-years`) and from a cold boot.

### Window type of each message reached

| Window type | Runs drawn | Entries | Original text, widest row | Original text, largest page | Source |
| --- | --- | --- | --- | --- | --- |
| 1 (`C0`) | 41 | 12 (the whole intro table `$E2:EE73`) | 12 slots | 24 slots | Cold boot, `intro-cold` route, poll 2, 18470 frames |
| 2 (`C1`) | 2 | 1 (`$E7:379B`, field message id 3) | 13 slots | 23 slots | `field` route, poll 1 |

On the untouched ROM the same runs are drawn with the same types (`intro-cold` at poll 2: the same 41 runs, each within 4 frames of the marker ROM; `field` at poll 1: the same frames).

Unreached entries are listed by the tool with their table and index (`report`, or `--json` for the whole list). They are, in the slice, 307 runs of the field table (113 entries) that the routes did not trigger. The whole intro table was reached. In the whole script 4729 runs are in the map of `--all`, of which only the 43 above were drawn.

### Slot limits (verified with rulers)

A ruler writes 40 slots into a run. The counter after the draw is the number of slots the window accepted.

| Ruler | Window type | Slots written | Slots drawn (counter) |
| --- | --- | --- | --- |
| `$E2:EE93` runs 0, 1, 2 | 1 | 40 | 24, 24, 24 |
| `$E2:EEE2` run 0 | 1 | 40 | 24 |
| `$E7:379B` runs 0, 1 | 2 | 40 | 32, 32 |

The hook consumes the tokens past the limit without drawing them, so the counter saturates at the limit: 24 in type 1, 32 in type 2. These are the same numbers as the draw tables in [window-types.md](window-types.md) and the hook's limits, now seen in the running game for the pages that the game really uses. The slots of a row (12 in type 1, 16 in type 2) come from the tilemap tables of the loops ([window-types.md](window-types.md#geometry)) and from the row model below, not from a ruler.

### Row model (verified for types 1 and 2)

`C3` starts the second row at slot 12 in type 1 and at slot 16 in type 2 (code, [window-types.md](window-types.md#line-break-and-skips)); `E5 nn` skips `nn` slots. For the original text of each run the tool computes the slots the page should take as `row start * (rows - 1) + last row` and compares it with the counter measured on the original ROM: 43 of 43 runs agree (none differ). Examples: a page of `[10, 11]` glyphs in type 1 ends at slot 23; `[0, 12]` at 24; `[13, 10]` in type 2 at 26.

### Opening command and window type (code, agreed by the runs)

The handler of `C0` (`$D1:0536`, then `$D1:2B62`) stores 1 in `$0A4C` at `$D1:2BAE`; the handler of `C1` (`$D1:056C`, then `$D1:2BC2`) stores 2 at `$D1:2C27` and clears `$0A47`. Every drawn run agrees: 41 `C0` runs in type 1 and 2 `C1` runs in type 2, none against the rule. The page layout of the script is then known statically for any run: the type is that of the last `C0`/`C1` before it in the skeleton.

Corpus, over the 4729 runs of the whole message script (`--all` map), by the command that opens the page:

| Opening command | Runs | Widest row (glyphs) | Runs with a row above 12 | Runs above the page limit of their type (24 slots in type 1, 32 in type 2) |
| --- | --- | --- | --- | --- |
| `C0` | 2909 | 13 | 9 | 4 (largest page 25 slots) |
| `C1` | 1819 | 15 | 190 | 0 (largest page 26 slots) |

The Japanese author of the `C0` pages kept to 12 glyphs a row (with a few exceptions to look at) and the `C1` pages use up to 15, as the two windows allow. No row goes above 16 and no run has more than two rows.

### Budgets

The budget of a Spanish run, in letters (2 per slot), is the slot limit of its window type times two:

| Window type | Opening command | Letters per row | Letters per page | Evidence |
| --- | --- | --- | --- | --- |
| 1 | `C0` | 24 | 48 | Measured (ruler) for the page; the row from the tilemap tables |
| 2 | `C1` | 32 | 64 | Measured (ruler) for the page; the row from the tilemap tables |

`tools/tour_messages.py budgets --map <map> --log <log>...` writes this for every run as JSON: `max` in letters, the window types seen, and the evidence, which is `measured` when the type was seen drawn in a ruler run, `code` when it was seen drawn but only the code limit is available, and `predicted` for a run that no tour reached (type from its opening command). A run with a type other than 1 and 2 gets no `max`. Stage 4 should copy `max` into the entries only where the evidence is not `predicted`, or accept the prediction knowingly.

## Not Reached

- **Field.** Only `$E7:379B` (message id 3, two runs, type 2) was reached. Four random walks of about 85 moves each and four directed variants of the known route (extra steps in one direction, with A pressed at the end) from `field-start` drew nothing else, so the 113 other entries of the table `$E7:362B` are unreached. The field runs that open with `C0` followed by `E7 xx yy` commands (`E7 14 01` is the commonest in the slice) are in this group: their window type is predicted to be 1 by the code of `C0`, but the `E7` command, whose handler was not read, may change the window; nobody has seen one drawn.
- **Other savestates.** Earlier in the session, the other savestates (character creation, name entry, `window-type-*`) were tried with A presses and drew no message; that was not re-measured for this document.
- **After the intro.** The cold route drew all 41 runs of the intro table and then went on pressing A; what comes after it (the first area) was not toured.
- **Window types 0, 3, 4, 5, 6** did not appear as the type of any drawn run.
- **The other 1,400 or so message entries** of the other areas, the event scripts, the global table and the called scripts are in the map of `--all` (messages only) and were not toured.

## Reproduce

```sh
export MESEN_FOR_AI_DIR=<workspace>/tools/mesen-for-ai PYTHONPATH=tools
python tools/build_marker_rom.py --rom <original.sfc> --asar <asar.exe> --table tbl/original.json --out <out>/marker.sfc --ruler E2:EE93 --ruler E2:EEE2 --ruler E7:379B
../../.venv/Scripts/python.exe tools/tour_messages.py run --rom <out>/marker.sfc --map <out>/marker.sfc.map.json --route field --savestates <workspace>/savestates --mesen-bin <Mesen.exe> --poll 1 --check-buffers --out <out>/field.log.json
../../.venv/Scripts/python.exe tools/tour_messages.py run --rom <out>/marker.sfc --map <out>/marker.sfc.map.json --route intro-cold --mesen-bin <Mesen.exe> --poll 2 --check-buffers --out <out>/intro.log.json
python tools/tour_messages.py report --map <out>/marker.sfc.map.json --log <out>/field.log.json --log <out>/intro.log.json
python tools/tour_messages.py budgets --map <out>/marker.sfc.map.json --log <out>/field.log.json --log <out>/intro.log.json --out <out>/budgets.json
python tools/build_marker_rom.py --rom <original.sfc> --table tbl/original.json --out <out>/original.map.json --map-only
```

The cold intro takes about 15 minutes at `--poll 2` (18470 frames). The logs and the ROMs stay outside the repository.

## Open Items

1. Reach more of the game. The route to a new message needs either a map of the area (positions are in WRAM, `$B89A` for X and `$B897` for Y, see [window-types.md](window-types.md#open-items)) or a savestate taken at each scene. A random walk is not enough.
2. Read the `E7` command (many field entries of the slice use it in forms such as `E7 14 01`) and find out whether it changes the window type of the `C0` page that follows it.
3. Window types 3 to 6 and their loops 3 to 5 ([window-types.md](window-types.md)): no run drawn in them was seen.
4. The nine `C0` runs with a row of 13 glyphs and the four above 24 slots in the type 1 model (in the whole script): the model says they overflow the narration window; either a window with more slots is used or the extra glyph wraps. Reach one and read its counter.
5. Run `--all` as a marker ROM from a cold boot through a long route, to see that the 1500 or so rewritten blobs do not break scripts that depend on offsets inside a blob (none is known).
6. A faster driver: a write watch on the top of the script stack would catch every run at any poll interval; polling every frame costs about 45 ms per frame.
7. Free space: the rulers use `$E2:F8A6`-`$E2:FFFF` and `$E7:FC81`-`$E7:FFFF` only because earlier spikes did. That nothing else reads them is still unverified (text-engine.md, Open Items 4).
