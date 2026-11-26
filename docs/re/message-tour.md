# Message Tour

Stage 3 of [../specs/translation-pipeline.md](../specs/translation-pipeline.md): a ROM where every text run is a readable marker, and a tour of the game that records, from RAM and not from the screen, which window type each message is drawn in. Notation follows [text-engine.md](text-engine.md): **verified** (observed in the emulator), **measured** (counted from the ROM or the logs), **corpus** (a pattern in the data), **guess** (with why). Tools: `tools/build_marker_rom.py`, `tools/tour_messages.py` and `tools/force_messages.py`, with tests in `tests/test_build_marker_rom.py`, `tests/test_tour_messages.py` and `tests/test_force_messages.py`.

## Verdict

Status: the method is **verified**; the window type of 4670 of the 4729 text runs of the message script is **measured**; the 59 left are listed below.

- The marker build works for the whole script, not only for the slice: with `--all` it marks every text run of every message entry that the extractor calls `ok` (4729 runs in 1548 entries), in place, with nothing relocated.
- Walking the game reached only 43 of the 350 runs of the slice. **Forced drawing** ([below](#forced-drawing)) replaced it: from one field savestate, each of the 1548 blobs is started by writing its ROM address into the script stack, and the engine draws it with its own code. 1536 entries were forced in the marker ROM at poll 2 (1500 frames at most each) and the 12 of the intro table in a second pass; 4670 runs were drawn and read from RAM, in the 12 tables that hold messages. A walked tour cannot do this, and it needs no map of the game.
- Window types seen in drawn runs: **1** (2856 runs, every one opened by `C0`) and **2** (1814 runs, every one opened by `C1`). The only exceptions are 2 `C0` runs recorded in type 2, which are a side effect of forcing (see Measurements). The type that the opening command sets is therefore **measured** for those runs, and the `E7` command between a `C0` and its text does not change it (176 runs, all type 1).
- A third type exists in the data: **3** was seen in every entry whose `C2` (yes/no choice) was reached (77 entries), and in no other. No run of text was drawn in it.
- The slot limit of each window was measured with rulers, now also through forced drawing: 24 slots (48 letters) per page in type 1 and 32 slots (64 letters) in type 2. The row model, extended to follow a page across its runs, predicted the counter of 412 of 413 runs of the original game that were drawn (the one difference is described below).
- **Pages above 24 slots are truncated, not wrapped.** The 4 `C0` runs whose model gives 25 slots were drawn in the original ROM with the counter at 24 (measured, 4 of 4): the last glyph is dropped. This agrees with the code (`$D1:4610` skips the draw when the counter reaches `$18`).
- `E7` is read from code ([E7 Command](#e7-command)): it selects the speaking actor and what the actor does; it does not touch the window.
- Not done: the 59 runs listed under Not Reached, the window types 0 and 4 to 6, and any run in a window other than the message windows.

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

The build takes about two seconds. The runs left as they were are the ones of one or two narrow glyphs. The entries that the extractor calls `review` (runs after `FE` or `E8`) are not touched. The slice was first driven by walking; the full ROM (`--all`) was then driven entry by entry by forced drawing (below).

## Tour

`tools/tour_messages.py run` drives MesenCE with a route, reads WRAM after every poll and writes a log. `report` analyses logs without the emulator (several logs can be merged), `budgets` writes the budget of every run and `walk` writes a random-walk route.

**Route as data.** A route is a JSON object (or an entry of `ROUTES` in the tool): a start (`{"state": "<file in the savestates directory>"}` or `{"reset": <frames>}` for a cold boot) and steps, each one `{"wait": n}` or `{"press": [buttons], "hold": n, "release": n, "times": n}`. It is validated before it runs. The built-in routes are `field` (from `field-start.mss`, 18 steps down and 16 left, then A), `intro` (from `intro-300-years.mss`, A every 60 frames) and `intro-cold` (reset, 600 frames, Start, A, then A every 60 frames for 300 presses).

**What is read.** After each poll the tool reads `$0A3C`-`$0ACF` and `$1D`-`$1F` with `cpu.read_memory` on `snesWorkRam`: the window type `$0A4C`, the slot counters `$0A45`, `$0A47`, `$0A49`, the message id `$0AC1`, the script pointer stack depth `$0A8D`, the pointer of the top level (3 bytes per level from `$0A8F`) and the command state `$0AC4`/`$0AC5`. Samples are logged when they change. The savestates and the ROM are inputs; nothing is written inside the repository.

**How a run is recognized (verified).** The text routine reads the glyphs through `$1D`-`$1F` but keeps the position of the script in the stack, and writes it back only when it reaches a command it does not handle itself (`$D1:459E`-`$D1:45A3`). So the top of the stack points at the first byte of the run while the run is drawn and at the command that follows it once it is drawn, and both addresses belong to that run alone. The frame-by-frame log of the original game in the field shows it: at frame 430 message id 3 is called with the pointer at the start of its blob; at frame 432 the window type is 2, the counter `$0A47` is 13 and the pointer is at the end of the first run (`$E7:37AE`); two frames later the pointer is past the next command (`C4`, waiting for a key); at frame 750, after A, the counter is 26 and the pointer is at the end of the second run (`$E7:37CD`). The counter is read in the sample in which the pointer is at the end of a run (the draw is done in one frame) and not before, because before it still holds the previous page. `$1D`-`$1F` is **not** a reliable copy of the script pointer outside the text loop: in the field it held `$F9:0000`, so the stack is used. text-engine.md calls it the active script pointer, which is true only inside the loops.

**Poll interval (verified).** The pointer stays at the end of a run for a few frames (the dispatcher takes one command per frame or two). With `--poll 4` a run that is followed at once by commands was missed (`$E7:379B` run 1 in the field; in the intro the poll-4 run of the original ROM saw 23 runs where the poll-2 run saw 27 with the same map). Use 1 or 2: a run reported as unreached with a larger poll may be a sampling miss.

**Runs on the untouched game (verified).** The same routes run on the original ROM with the map of `--map-only`. The window type and message id of each run are the same as in the marker ROM, and the draw frames are the same in the field (432 and 749) and within 4 frames in the cold intro (poll of 2 frames; the intro waits on timers and presses). So the marker ROM does not change which window opens; it changes only what is drawn. The original-ROM tour is also what measures the row model below.

**Text read back from RAM (verified).** With `--check-buffers`, when a marker run is drawn the tool reads the tile buffer of each slot from WRAM (the buffer address table of the loop, `$D1:46DB` or `$D1:48B3`, 32 bytes at the buffer and 32 at `+0x100`) and compares it with the two font letters of the marker. The check passed for 6 marker runs of the first build (2 in type 2 in the field, 4 in type 1 in the intro) and for 36 of 37 runs of the cold intro. The 37th (`$E2:F36F` run 1) was reported as wrong because the first version of the check assumed that the marker starts at slot 0, while that run follows another run on the same page (the counter was 5 for a 4-slot marker). The check now starts at the counter minus the marker length. That fix is covered by unit tests but the 18000-frame route was not run again in the emulator, so for that one run the evidence is only a guess that fits the counter. Ruler runs are not checked. So the markers do show their ids and no screenshot was needed.

**Sessions.** MesenCE sessions started at the same moment failed with `WinError 10048` in the first passes (the local bridge port is chosen, released and only then bound by the emulator). The tool retries on that error. On 2026-11-26 the failure did not reproduce: 24 simultaneous startups, three sessions polling while 15 others started, and three `--shard` runs of `force_messages.py` at once all finished without it. The cause was not identified; the bridge client opens one TCP connection per request (about 40 per second per session), which is a suspect that was not confirmed. Shards are usable; if `10048` returns, fall back to one session at a time.

## Forced Drawing

`tools/force_messages.py` draws any blob of the map on demand, without walking to it. Status: **verified** on the field savestate for the blobs listed under Measurements.

**Why it works (code, then verified).** The field main loop (`$C3:7B3A`) calls the script dispatcher `JSL $D1:0000` only while the byte `$40` is 2 (event running); with `$40` = 1 (walking) it does not call it, which is why writing a script pointer alone does nothing in `field-start`. `$D1:0000` jumps on `$0AC3` through a table (`$D1:000F`): mode 1 waits for an event (it reads the trigger queue behind `$BA`, resolves the message id with `$D1:3A54` and moves to mode 2), mode 2 runs the command state machine at `$D1:0274` with the script at the top of the pointer stack. When the script ends the loop goes back to `$0AC3` = 1 and `$40` = 1. So the tool writes, from a loaded `field-start`: the 3-byte pointer of the blob (its address in the ROM, nothing is copied) at stack level `$0A8D`, the message id `$0AC1`, `$0A4C` = 0 (window closed), `$0AC3` = 2, `$0AC4`-`$0ACA` = 0 and `$40` = 2. The engine then draws the blob with its own code. Because the pointer is a ROM address, the map identifies each run exactly as in a walked tour, and the log is a normal tour log: `tour_messages.py report` and `budgets` read it.

**Driver.** One savestate load per entry (so entries cannot influence each other), then one frame at a time (`--poll` 2 by default) reading `$0A3C`-`$0ACF` in a single call; A is held 2 frames out of every 12 to pass key waits. The entry has finished when `$0AC3` leaves 2 (`finished`), or after `--max-frames` (`timeout`). A call that fails in the emulator repeats the entry in a new session and, if it fails twice, records it as `error`. The log carries a `forced` list (id, address, message id, outcome, frames, window types opened); `0` (closed window) is not counted as a type. `--resume` continues a log, `--shard I/N` splits a selection (but not across simultaneous sessions, see below), `plan` lists a selection without the emulator and `summary` aggregates logs.

**Limits.**

- The state is always the field in area 0. Text drawing does not depend on the area, but anything a blob does besides text (a nested message through `EE` or `C2`, a map change `D9`) runs in that state. Message ids that a script calls by id are resolved with the tables of area 0.
- The first window of a forced blob opens in whatever the screen mode is: in type 1 the loop writes the narration tilemap addresses, which are not the ones of the 512-dot field screen, so the pixels are meaningless; the RAM counters and tile buffers are not affected and are what is read.
- Only the message role of the map is covered (1548 entries). Event, global and called scripts are not in the map.
- A full pass of all 1548 entries takes about 40 minutes in one session at poll 2. Three parallel shards forced 38 entries each in about 35 seconds without `WinError 10048` (see Sessions), so a sharded pass should be faster; it was not timed over the whole map.

## E7 Command

`E7 xx yy` (handler `$D1:08AF`, two arguments, measured arity). Status: **read from code**; the effect on the window type is also **measured** (below).

- **Actors.** The field keeps 16 actor records of `$20` bytes from `$B880` (the search at `$C0:2470` walks `$B880`-`$BA7F`): byte 0 is the actor id, byte 6 a state (1 is idle), byte `$11` the facing. The player's record is the first (`$B891` is its facing, the position bytes `$B89A`/`$B897` are in it).
- **Selecting.** `xx` of 0 releases the current speaker (`$D1:4E2F`) and stores `yy` in `$0ADD`. Otherwise `xx` of `$F0` or more is first mapped by `$D1:4E58`: `FE`, `FD`, `FC`, `FB` are the party members 0 to 3 and take their actor id from `$098A + n`; then the record whose id is `xx` is looked up. If it exists it becomes the current speaker `$0ADB` (the previous speaker is released first, state `$0A`, `$D1:2267`) and `yy` goes to `$0ADD`; if it does not exist the command only consumes `yy`.
- **Effect.** `$0ADE` counts the glyphs drawn (the text loops increment it). At the start of each dispatcher step `$D1:4DD0` acts on the speaker once text has been drawn: it saves the 32-byte record at `$0ADF`, puts the actor back in the idle state, and, by `yy`, sets its facing from the player's (`$B891` through the table at `$C0:2602`, which looks like the opposite direction) for `yy` = 0, leaves the facing for `yy` = 1, and sets it and also keeps it in `$0AF0` for `yy` of 2 or more. In short: the actor `xx` is the one who speaks, and `yy` says whether it turns to the player (**guess** for that reading; the memory it moves is read from code).
- **It does not touch the window.** None of these paths writes `$0A4C`, the slot counters, the tilemap or the position of the box, so the window type of the page that follows comes only from the `C0` or `C1` that opens it. This agrees with the forced draws: every run drawn after an `E7` between its opening command and itself (the count is in Measurements) was in the type that its opening command sets.

## Measurements

Run on 2026-11-25 and 2026-11-26 with the workspace savestates (`field-start`, `intro-300-years`) and from a cold boot. Evidence levels: **measured** (read from RAM in the running game), **code** (read from the disassembly), **predicted** (from the opening command), **guess**.

### Forced drawing, marker ROM (measured)

The marker ROM was built with `--all` and the three rulers (`E2:EE93`, `E2:EEE2`, `E7:379B`). The 1536 entries of the 11 tables other than the intro table were forced at poll 2 with 300 frames at most; the 75 that had not finished were forced again with 1500 frames (54 finished); the 12 entries of the intro table (`$E2:EE73`, long waits) were forced with 1500 frames. Window type of the runs drawn, by table of origin:

| Table | Runs in the map | Runs drawn | Type 1 | Type 2 |
| --- | --- | --- | --- | --- |
| `$E2:EE73` (intro, area 8) | 41 | 32 | 32 | 0 |
| `$E7:003F` | 360 | 335 | 239 | 96 |
| `$E7:362B` (first field area) | 309 | 294 | 183 | 111 |
| `$EC:0027` | 373 | 373 | 150 | 223 |
| `$ED:002F` | 514 | 514 | 319 | 195 |
| `$ED:43B3` | 518 | 518 | 333 | 185 |
| `$EE:24E2` | 174 | 164 | 110 | 54 |
| `$EE:3C05` | 431 | 431 | 284 | 147 |
| `$EE:84F6` | 661 | 661 | 447 | 214 |
| `$EF:0089` | 502 | 502 | 215 | 287 |
| `$EF:4447` | 424 | 424 | 289 | 135 |
| `$EF:8515` | 422 | 422 | 255 | 167 |
| Total | 4729 | 4670 | 2856 | 1814 |

The 2 runs recorded in both types are counted once in each. The earlier cold-boot tour had drawn all 41 runs of the intro table (type 1), so 4679 runs have a measured type. The opening command and the window type agree in every run but two:

| Opening command | Window type seen | Runs |
| --- | --- | --- |
| `C0` | 1 | 2856 |
| `C1` | 2 | 1812 |
| `C0` | 2 | 2 |

The 2 `C0` runs in type 2 (`$E7:13A0` run 7 and `$E7:100C` run 1) were drawn while a script of another entry was running (the message id in RAM was 222 and 217, the ids of other entries; a `C9`, `CD` or `EA` command of those scripts leads to other scripts of the area-0 field state, which then draw these blobs), with a type-2 window still open. They are **not** evidence that `C0` opens type 2: the read-back of the marker from the tile buffers was wrong for exactly these two runs (it looked for the type-2 layout), so the type recorded at the sample is not the window the text was drawn in. `$E7:0E55` run 15 was recorded in type 2 in one of the passes for the same reason. For budgets the tool takes the smaller of the two limits for a run seen in two types.

Window types opened by an entry (types other than 0 seen in any sample after the engine started the blob): type 1 only in 35 entries, type 2 only in 52, types 1 and 2 in 1361 (a blob with `C0` and `C1` pages), type 3 in 77 and no type at all in 10 (blobs that start with setup commands such as `F2`, `EF` and `EE` and waited until the frame limit before any window opened; all 10 timed out). **Type 3 appears in exactly the entries that contain `C2`** (77 of 77 where a `C2` was reached; the one entry with a `C2` that did not show it, `$ED:0873`, timed out before reaching it). `C2` writes 3 to `$0A4C` at `$D1:0579` (code), so type 3 is the yes/no box; no run of text was drawn in it. The value 80 (`$50`) also appears in 6 entries after a `C2` or an `EE`: it is an artifact of forcing (the message id that the script calls is resolved in the tables of area 0, points outside the script data, and the engine reads WRAM at `$20:0000` as if it were a script), not a window type.

`E7` and the window type: 176 runs were drawn with an `E7` between their `C0` and the run, all in type 1 (measured). With the code ([E7 Command](#e7-command)) this settles that `E7` does not change the window.

Marker text read back from the WRAM tile buffers: 1292 runs checked, 1290 correct, the 2 wrong are the 2 runs above.

### Runs not drawn

59 of 4729 runs, in entries that did not finish (they wait longer than 1500 frames or for something that the forced state never gives), or in a branch that the forced run did not take: 9 of the intro table (`$E2:EF50`, `$E2:F1FE`), 25 of `$E7:003F`, 15 of `$E7:362B`, 10 of `$EE:24E2`. The largest are `$E7:41F2` (15 runs), `$E7:1119` (11), `$E7:100C` (10), `$EE:3258` (6, among them the only run with no `C0`/`C1` before it and three rows, `[0, 13, 13]`) and `$EE:2E04` (4). Their window type is **predicted** from their opening command (58 of them) and unknown for the run with no opener.

### Event and global scripts (measured, 2026-11-26)

`build_marker_rom.py --roles events,global` marks the scripts that hold text outside the message tables: 141 entries with 261 runs (123 global entries with 234 runs and 19 event entries with 28 runs; the called scripts hold no text). Of the 261 runs, 221 get a marker and 40 are shorter than 3 bytes and stay as they were. The marker ROM builds and runs, and three parallel `force_messages.py` shards forced all 141 entries in about 20 seconds.

- Window type: every entry that opened a window opened type 2 (99 entries), type 1 and 2 (37 entries; they hold both a `C0` and a `C1`), or type 2 and then 3 (1 entry, `$E7:551B`, which has a `C2`). Four entries opened none.
- Runs drawn: 74 of 261, all in type 2. 135 of 141 entries finished; 6 timed out at 300 frames (`$ED:2C6B`, `$ED:7AD4`, `$ED:8425`, `$EF:31B9`, `$EF:B02E`, `$EF:C45D`).
- Not drawn: 86 entries (82 of them in the global table `$EF:C1FB`) opened their window but the log never reached a marker. The cause is not known: either their text is drawn by a path that does not leave the script pointer at the run, or their branches depend on a game state that the field start does not give. For these runs the window type is known per entry (the opening command) and the slot limits are the same, so the budgets hold, but no run has its own measured counter.

### Slot limits (measured with rulers, by walking and by forcing)

A ruler writes 40 slots into a run. The counter after the draw is the number of slots the window accepted.

| Ruler | Window type | Slots written | Slots drawn (counter) |
| --- | --- | --- | --- |
| `$E2:EE93` runs 0, 1, 2 | 1 | 40 | 24, 24, 24 |
| `$E2:EEE2` run 0 | 1 | 40 | 24 |
| `$E7:379B` runs 0, 1 | 2 | 40 | 32, 32 |

The rulers were first measured by walking; the forced pass reproduced the same counters. The hook consumes the tokens past the limit without drawing them, so the counter saturates at the limit: 24 in type 1, 32 in type 2. The slots of a row (12 in type 1, 16 in type 2) come from the tilemap tables of the loops ([window-types.md](window-types.md#geometry)) and from the row model below, not from a ruler.

### Row model and pages above the limit (measured on the original ROM)

`C3` starts the second row at slot 12 in type 1 and at slot 16 in type 2 (code, [window-types.md](window-types.md#line-break-and-skips)); `E5 nn` skips `nn` slots; `C0` and `C1` start the page at slot 0. The tool follows a page through its skeleton (`predict_page_counters`): a run adds its first row, each `C3` inside it jumps to the row start plus the next row, a `C3` or an `E5` between runs does the same, a page continues across runs that have no opening command between them, and the counter stops at the window limit. It compares the prediction with the counter measured on the original ROM: 413 runs forced on the untouched game (the 126 entries of the slice, `$E7:362B` and `$E2:EE73`, and the 10 entries that hold the widest pages), **412 agree**. The difference is `$E7:0F8C` run 6, measured 21 and predicted 20: the run follows an `E9` command, which copies a string into the text buffer and probably draws one more slot (**guess**).

The four `C0` runs whose rows give 25 slots (`$E7:0F8C` run 1, `$E7:1480` run 1, `$ED:17D9` run 13, `$EE:A1F9` run 0; rows `[0, 13]` or `[12, 13]`) were drawn with the counter at 24 on the original ROM (**measured**, 4 of 4): the page is **truncated**, the 25th glyph is not drawn and nothing wraps. This closes the open item about them in the earlier version of this document. The widest `C1` pages in type 2 reach 30 slots (`$E7:3868`, rows `[13, 14]`), under the limit of 32.

### Opening command and window type (code, measured)

The handler of `C0` (`$D1:0536`, then `$D1:2B62`) stores 1 in `$0A4C` at `$D1:2BAE` (after choosing a value for `$7B` by `$0094` being `$DE`, `$DD` or other); the handler of `C1` (`$D1:056C`, then `$D1:2BC2`) stores 2 at `$D1:2C27` and clears `$0A47`; `C2` stores 3. The forced runs agree for 4668 of 4670 runs, the other two being the artifact above. The page layout of the script is then known statically for any run: the type is that of the last `C0`/`C1` before it in the skeleton.

Corpus, over the 4729 runs of the whole message script (`--all` map), by the command that opens the page:

| Opening command | Runs | Widest row (glyphs) | Runs with a row above 12 | Runs above the page limit of their type (24 slots in type 1, 32 in type 2) |
| --- | --- | --- | --- | --- |
| `C0` | 2909 | 13 | 9 | 4 (largest page 25 slots) |
| `C1` | 1819 | 15 | 190 | 0 (largest page 26 slots) |

The Japanese author of the `C0` pages kept to 12 glyphs a row (with a few exceptions to look at) and the `C1` pages use up to 15, as the two windows allow. No row goes above 16 and no run has more than two rows, except the one run without an opener.

### Budgets

The budget of a Spanish run, in letters (2 per slot), is the slot limit of its window type times two:

| Window type | Opening command | Letters per row | Letters per page | Evidence |
| --- | --- | --- | --- | --- |
| 1 | `C0` | 24 | 48 | Measured (ruler) for the page; the row from the tilemap tables |
| 2 | `C1` | 32 | 64 | Measured (ruler) for the page; the row from the tilemap tables |

`tools/tour_messages.py budgets --map <map> --log <log>...` writes this for every run as JSON: `max` in letters, the window types seen, and the evidence, which is `measured` when the type was seen drawn and its limit was measured with a ruler, `code` when it was seen drawn but only the code limit is available, and `predicted` for a run that no tour reached (type from its opening command). With the logs of this section the budget file has 4670 runs `measured` (2855 type 1 with 48, 1812 type 2 with 64, 3 seen in both types with 48), 58 `predicted` (51 type 1, 7 type 2) and no entry for the run with no opener. Stage 4 should copy `max` into the entries only where the evidence is not `predicted`, or accept the prediction knowingly. The letters per row are a layout choice for stage 4, not a limit of the engine: a page is drawn as a continuous string of slots and `C3` only moves the cursor to the second row.

## Not Reached

- **59 runs** (above): their window type is predicted. A longer wait, a savestate in a state that gives the script what it waits for, or a route could draw them.
- **Window types 0, 4, 5, 6** did not appear as the type of any drawn run, and no run of text was drawn in type 3 (the `C2` choice box). The loops 3 to 5 of [window-types.md](window-types.md) were not seen at all.
- **Forced drawing starts from one state** (the first field area, `field-start`). A blob that calls other messages (`EE`, `C2`, `E8`) or scripts runs them with the tables of area 0, so what a script does besides drawing its own text is not representative. The window type of the text is: it is fixed by the opening command and was confirmed on the runs of every table.
- **Only messages are in the map.** The event scripts (`T1`), the global table (`T2`, 123 entries with text) and the called scripts are not in the map of `--all`, so their text runs are not marked or toured.
- **Other text paths** (menus, status, shops, battle, the name grid) draw without a message blob; see [window-types.md](window-types.md#other-text-paths).
- **Walked routes** were not extended: forced drawing replaced them, and a map-aware walking route is no longer needed for the window type. It would still be needed to see a message in its real surroundings (the screen mode, the speaker, the pixels), which is outside what this stage measures.

## Reproduce

```sh
export MESEN_FOR_AI_DIR=<workspace>/tools/mesen-for-ai PYTHONPATH=tools
python tools/build_marker_rom.py --rom <original.sfc> --asar <asar.exe> --table tbl/original.json --out <out>/marker-all.sfc --all --ruler E2:EE93 --ruler E2:EEE2 --ruler E7:379B
python tools/build_marker_rom.py --rom <original.sfc> --table tbl/original.json --out <out>/original-all.map.json --map-only --all
python tools/force_messages.py plan --map <out>/marker-all.sfc.map.json --table E7362B
../../.venv/Scripts/python.exe tools/force_messages.py run --rom <out>/marker-all.sfc --map <out>/marker-all.sfc.map.json --savestates <workspace>/savestates --mesen-bin <Mesen.exe> --table E7362B --check-buffers --out <out>/field.log.json
../../.venv/Scripts/python.exe tools/force_messages.py run --rom <out>/marker-all.sfc --map <out>/marker-all.sfc.map.json --savestates <workspace>/savestates --mesen-bin <Mesen.exe> --max-frames 300 --check-buffers --save-every 50 --out <out>/all.log.json
../../.venv/Scripts/python.exe tools/force_messages.py run --rom <original.sfc> --map <out>/original-all.map.json --savestates <workspace>/savestates --mesen-bin <Mesen.exe> --table E7362B --max-frames 1500 --out <out>/original-field.log.json
python tools/build_marker_rom.py --rom <original.sfc> --asar <asar.exe> --table tbl/original.json --out <out>/marker-other.sfc --all --roles events,global
for s in 0 1 2; do python tools/force_messages.py run --rom <out>/marker-other.sfc --map <out>/marker-other.sfc.map.json --savestates <workspace>/savestates --mesen-bin <Mesen.exe> --shard $s/3 --max-frames 300 --check-buffers --out <out>/other$s.json & done
python tools/force_messages.py summary --map <out>/marker-all.sfc.map.json --log <out>/all.log.json
python tools/tour_messages.py report --map <out>/original-all.map.json --log <out>/original-field.log.json
python tools/tour_messages.py budgets --map <out>/marker-all.sfc.map.json --log <out>/all.log.json --out <out>/budgets.json
```

Without `--table` the whole map is forced (1548 entries); the full pass at `--max-frames 300` takes about 45 minutes. Run it in one process (`--resume` continues an interrupted log) and force the entries that did not finish again with `--entry ID --max-frames 1500` into another log, then pass both logs to `summary` and `budgets`. The walked tours are reproduced as before (`tour_messages.py run --route field` and `--route intro-cold`, see Tour). The logs and the ROMs stay outside the repository.

## Open Items

1. Draw the 59 runs that were not drawn (waits longer than 1500 frames, scripts that wait for a state that the field start does not give). They are 1.2% of the runs and carry a predicted type.
2. Window types 4 to 6 and their loops 3 to 5 ([window-types.md](window-types.md)), and the loop that draws the options of the `C2` box (type 3): no text run was seen in them. They are the candidates for shops, battle and portrait dialogue and will need the other text paths.
3. Understand why 86 event and global entries opened a window without the log reaching a marker (see Event and global scripts), and give them a run-level measurement.
4. A forced pass from other savestates (one per area, or the intro) for the blobs that call other messages, to see them with the tables of their own area.
5. `E9`, `F6` and `CD`: `E9 nn` copies a string into `$0A4D` and probably draws a slot (1 slot of difference in `$E7:0F8C` run 6), `F6 nn` appears between runs of one page (the counters agree with it drawing nothing); neither was read. Not needed for the budgets.
6. Forced drawing ran all 1548 rewritten blobs of the `--all` marker ROM through the engine in place (4670 runs drawn, none broken); scripts that depend on offsets inside a blob (none is known) are not covered by it.
7. A faster driver: a write watch on the top of the script stack would catch every run at any poll interval; polling costs about 15 ms per call, one call per poll.
8. Free space: the rulers use `$E2:F8A6`-`$E2:FFFF` and `$E7:FC81`-`$E7:FFFF` only because earlier spikes did. That nothing else reads them is still unverified (text-engine.md, Open Items 4).
9. The `WinError 10048` seen in the first passes is not reproducible now; time a full sharded pass and keep the retry in case it comes back.
