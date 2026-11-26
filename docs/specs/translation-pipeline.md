# Translation Pipeline Specification

Status: active

Labels: experimental

This document specifies how the Spanish script gets from the game's Japanese dialogue into a patch. The seven decisions in [Decisions](#decisions) were accepted by the user on 2026-11-25 as recommended, and the eighth (provisional budgets) the same day. Claims follow the convention of [../re/text-engine.md](../re/text-engine.md): **verified** (observed in the ROM or the emulator), **measured** (computed from the ROM or the corpus), **corpus** (a pattern in the data), **guess** (with why).

## Scope

In scope for the first version: the dialogue messages of the area tables (`T0`, ids below `0x200`, 1654 blobs of which 1628 close exactly), drawn by the two text loops that have the hook (window types 1 and 2, see [../re/window-types.md](../re/window-types.md)), with the project font ([../fonts/decision.md](../fonts/decision.md)).

Out of scope for the first version, each of which needs its own analysis: text that does not go through these scripts (title menu, item and spell names, status screens, battle messages, see Open Items 5 of text-engine.md), the window types 3 to 6, proportional spacing, and any change to the graphics.

## What Exists

| Piece | State | Where |
| --- | --- | --- |
| Command codec: tokenize and encode with argument counts and evidence level | Done, **verified** by an identity build (encode of decode is the original, every table) | `tools/script_format.py`, `tools/check_scripts.py` |
| Pointer tables, area records and blob relocation with a write log | Done, **verified** by a relocation probe in the emulator | `tools/script_format.py`, `tools/script_builder.py` |
| Hook that draws two Latin letters per glyph slot (`F9 a b`), 115 letters | Done, **verified** in window types 1 and 2 | `asm/latin_pair_hook.asm`, `tools/build_latin_probe.py` |
| Project font and its outline | Done | `assets/font/latin-8x16.txt`, `tools/build_custom_font.py` |
| Probe that replaces one message with Spanish text | Done (a spike, one message) | `tools/build_latin_probe.py` |
| Glyph table (which character each Japanese glyph is) | Done for the 920 glyphs in use, 4 readings open | `tbl/original.json`, `tools/glyph_table.py`, `tools/glyph_font.py`, [../re/glyph-table.md](../re/glyph-table.md) |
| Extractor: text files with skeleton and runs, coverage and round trip | Done, with 350 text entries flagged for review (runs after `FE`/`E8`) | `tools/extract_script.py` |
| Spanish encoder, placement, builder for the whole script, release | **Missing** | this document (stages 5 to 8) |

## Blocking Unknowns

1. **The Japanese text** can be read since stage 1 ([../re/glyph-table.md](../re/glyph-table.md)), with four readings open and no second reader yet. This was the first blocker; it is resolved apart from those items.
2. **The window type of each message is decided at run time** by the commands around it, not by the message (latin-font-spike.md). The row width (12 or 16 slots, 24 or 32 letters) and the line-break rule depend on it.
3. **Capacity.** See [Placement And Capacity](#placement-and-capacity): the Spanish text is several times larger than the Japanese one and the text banks have almost no free space.
4. **Unmeasured commands.** `CB DA DB E6 E8 EC ED FE` have **guess** or **unknown** argument counts; 199 blobs (26 of the messages) need them settled before they can be trusted.
5. **Readers of the tables.** Whether code other than `$D1:3A54` and the `D8` handler builds message addresses was not searched; moving blobs without knowing that is a risk (text-engine.md, Open Items 3).

## Pipeline

Each stage has a deliverable and a "done when". A stage does not start before the previous one passes.

1. **Glyph table** (done 2026-11-25, see [../re/glyph-table.md](../re/glyph-table.md)). A tool renders the font pages as sheets of numbered glyphs; each glyph gets a character, a confidence (`seen`, `matched`, `uncertain`) and the source of the judgement (visual reading, template match, English patch). The user reviews the uncertain ones. Output: `tbl/original.json`. Done when every glyph that the extracted text uses has a character or is marked `unknown`, with the count of each.
2. **Extract** (first version done 2026-11-25, see [../re/text-engine.md](../re/text-engine.md#extraction)). Every message of every table becomes a JSON entry (see [Text File Format](#text-file-format)). The dump never overwrites a translation. Done when the coverage test reproduces `check_scripts.py` (1628 exact blobs and the 26 flagged ones listed, none dropped) and `encode(decode(blob))` is the original for every entry.
3. **Marker build and tour.** Every message is replaced by its id; the game runs a scripted tour that logs, from RAM and not from the screen, the window type (`$0A4C`), the message id (`$0AC1`) and the slot counters each time a message draws. Output: the measured window type and page layout of each message that the tour reached, and the list of the ones it did not. Done when the budgets of the types 1 and 2 are measured and every unreached message is listed with its table and index.
4. **Translation.** Against `glossary.md` and the budgets, one `es` field per text run. The glossary and the translation are deliverables of the project, written in Spanish.
5. **Encode.** The tool turns each `es` run into Latin tokens (rules below) and checks the budget. Done when every entry encodes or fails with its id and the reason.
6. **Place.** The tool lays out the new blobs and tables in free space and repoints them (see [Placement And Capacity](#placement-and-capacity)). Done when the write log shows only expected ranges and the identity build (no edits) is still byte-identical.
7. **Build and check.** One entry point builds the ROM from the original and the text files and runs the checks. Done when the checks pass and the tour reaches every translated message without a freeze.
8. **Release.** A BPS patch against the clean original, applied again and compared, the original's hash recorded, the SNES checksum fixed here and not in the build, and the application steps in the Spanish `README.md`. Publishing is the user's decision.

## Text File Format

JSON, one file per message table (`text/<bank>-<table address>-<role>.json`), `indent=1`, `ensure_ascii=False`, `
` newlines, written by `tools/extract_script.py`. Only the entries that have text are written. The files hold the original Japanese text, so `/text/` is ignored by git until the project decides how translation files are published. Every entry:

```json
{
 "id": "E2:EE93",
 "role": "messages",
 "slots": ["E2EE73#0"],
 "size": 79,
 "status": "ok",
 "problems": [],
 "skeleton": "<C0>{0}<C8 80><C8 E0><C5><C8 3C><C0>{1}<C8 80><FF>",
 "runs": [
  {"raw": "00 00 AB A8 A8 FD CB FD 60 9E 9E 9E", "jp": "　　３００年前・・・", "es": "", "status": "todo", "max": null}
 ]
}
```

- The `id` is the address of the blob. `slots` lists the pointer slots (`table#index`) that point to it: several slots can share one blob (the one-byte `FF` blob). `size` is its length in bytes.
- A message is a **skeleton** of commands (`<hex>` tokens) with numbered holes `{n}` plus the **runs** of text that fill them. The translator edits only `es`; the commands, their order and their arguments are never retyped, so a waiting time or an effect cannot be damaged by a translation.
- A run is a sequence of glyphs with line breaks (`C3`, written `
`) and indents (`E5 nn`, written `<E5 02>`) between them, with at least one visible glyph. `raw` is the original bytes and the source of truth; `jp` is derived from it with the glyph table (a glyph with no character is written `[40]`, and a glyph whose character is shared with another is written `[FA 2A]`) and parses back to `raw`.
- Leading and trailing spaces belong to the text. Entries that decode as text but are data (a magic string the code compares) will be marked `"status": "data"` and are not translated.
- `status` of an entry is `ok` or `review`; `problems` says why (no terminator, a gap before the next blob, commands of unknown length, a run right after `FE` or `E8`). A `review` entry is extracted but not rewritten until it is resolved.
- `max` is the budget of the run's window and is filled by stage 3 (`measured`) or by the type's known size (`guess`); a run with no budget cannot be marked `done`.
- Regenerating with `--force` keeps `es`, `status` and `max` of every run whose `raw` is unchanged and refuses to overwrite a file without it.

## Spanish Encoding

- **Letters.** Each pair of letters is one token `F9 a b` and takes one glyph slot, 3 bytes for 2 letters (**verified**). A line with an odd number of letters is padded with a space, as the current encoder does.
- **Character set.** The 115 letters of the font (`LATIN_CHARS`: ASCII from the space, `ñÑ¿¡áéíóúüÁÉÍÓÚÜ` and `— … « »`). Any other character is an error that names the entry; there is no silent replacement.
- **Lines.** `\n` in `es` is a line break within the run. The tool breaks long lines at spaces to the letters-per-row of the window type; it never breaks a word and it fails if a word does not fit. In window type 1 the second row begins after 12 slots whether or not the break command was sent (**verified**), so a first row that is exactly full takes no break command.
- **Pages.** A run is one page. The translator splits long text into several runs; the tool does not paginate by itself. Where the original separated two pages with a wait command, the skeleton keeps it. Adding a page break that the original did not have is allowed only after the command that gives a page break has been verified in the emulator (`C4` then `C1`, **corpus**, not verified).
- **Budget.** Letters per page are rows times letters per row (48 in window type 1, 64 in type 2, both **verified** limits of the hook). The corpus maximum of 27 Japanese slots per page is above the 24 of type 1, so a message that long can only be in a window of 32 slots (**guess**).
- **Japanese kept.** Text that is not translated stays in its original tokens; the font is not changed, so the Japanese glyphs and the Latin letters coexist (**verified** in the spike).

## Placement And Capacity

**Measured:** the exact `T0` blobs hold 75018 bytes of glyph codes in 4394 pages, 14.6 slots per page on average (latin-font-spike.md). A page in Spanish costs 3 bytes per 2 letters; with 35 to 50 letters per page, a **guess** from the width of the windows and not from any translation, a page takes 50 to 75 bytes against 15 to 20 in Japanese, so the script grows by a factor of 3 to 5, about 225 to 375 KB.

**Measured:** a scan of the 4 MiB original finds 59 runs of `0xFF` of at least 256 bytes (586437 bytes in all) and 38 of at least 2 KiB (564757 bytes). The banks of the text tables hold little of it: about 1.8 KB in `$E2`, 1.3 KB in `$E3`, 1.3 KB in `$E5`, 2.1 KB in `$EE` and 11.4 KB in `$EF`, while `$DB` has 77 KB, `$DE` 39 KB, `$CD` and `$CE` about 31 KB each and `$D1` 33 KB. That `0xFF` bytes are unused is **not verified**: it needs trap bytes across a long route (text-engine.md, Open Items 4).

A table entry is a 16-bit address in the bank of its table, so a blob cannot leave its bank while its table stays. The area record holds a long pointer to each table, so a whole table can move: the tool writes a new table and its blobs in another bank and repoints the long pointer in the area record.

| Option | What it does | Cost and risk |
| --- | --- | --- |
| A. Move whole tables to banks with verified free space | New table and blobs per area in another bank; the area record is repointed. | Needs the free space verified and the readers of the tables found (Blocking Unknowns 3 and 5); no change to the header. Enough room if the `0xFF` runs are really free. |
| B. Extend the ROM | 6 or 8 MiB with the ExHiROM mapping, new text in the new banks. | Changes the header, the mapping and the checksum; every emulator and flash cart must support it; the engine's bank assumptions are unknown. |
| C. Denser encoding | A token that carries a run of letters (`F9 n b1 … bn`, about 1.05 bytes per letter against 1.5) and, later, a dictionary. | A change to the hook and its tests; shrinks the script by about a third. Worth it only if A runs short. |

Recommendation: **A first**, with a size report on the first translated area to replace the guess above with a measurement, **C if A runs short**, B only if both do. The tool refuses to write outside a free range that the recon has verified and fails on overflow; it never wraps.

## Checks

- Identity build: no edits, byte-identical output (kept green from the first commit of the builder).
- Round trip: `encode(decode(x)) == x` for every blob; the skeleton of a translated message equals the original's command by command.
- Coverage: every pointer table entry is accounted for; no message is dropped or duplicated; the blobs that do not close are listed.
- Write log: every changed byte has a write behind it, expected from the clean original, with no overlaps and every pointer decoded and asserted before it is overwritten.
- Budget: every run fits its window; no unknown character; no word wider than the row.
- Glossary: every term in `glossary.md` is written in its one agreed form (a check of the text, with the exceptions listed).
- Emulator: the tour reaches every translated message and logs, from RAM, no freeze; a cold boot after any code or font change, not a savestate.

## Repository Layout

```
tbl/           original.json (glyph table, with confidence)
text/          one JSON file per table
glossary.md    names and terms, one agreed form each (Spanish)
tools/         extract, encode, build, check, release, with tests
docs/specs/    this specification
docs/decisions/  durable decisions (capacity strategy, file format)
build/ work/   generated output, ignored by git
```

The real layout is decided when the first tool is written and then recorded here.

## Decisions

Accepted by the user on 2026-11-25 ("adelante con tus recomendaciones"). A change to one of them is recorded here first.

| # | Decision | Accepted |
| --- | --- | --- |
| 1 | Scope of the first version | Dialogue messages only (`T0`); menus, items and battle text after the pipeline works. |
| 2 | Capacity strategy | A, then C; B only as a last resort. Record it in `docs/decisions/` once the first area gives a measurement. |
| 3 | How the glyph table is made | Visual reading by the agent, cross-checked with template matching and the English patch, each glyph with its confidence; the user reviews the uncertain ones. |
| 4 | Unit of translation | The text run (a page), with the command skeleton fixed. |
| 5 | Pagination | The translator splits pages; the tool wraps lines and fails on overflow. |
| 6 | Text file format | JSON as above, one file per table. |
| 7 | Order of work | Glyph table first (it unblocks reading), then extract and identity, then the marker tour, then translation of one area as a vertical slice before the rest. |
| 8 | Provisional budgets (accepted 2026-11-25) | The opener of a page fixes its window type (`C0` gives type 1, `C1` gives type 2) and the measured limits are the budgets: 24 slots (48 letters) per page in type 1 and 32 slots (64 letters) in type 2, with the second row starting at slot 12 and 16. Each budget keeps its evidence level (measured, code, predicted, see [../re/message-tour.md](../re/message-tour.md)); a predicted one is replaced by a measurement when the tour reaches the run. On 2026-11-26 the user accepted the 58 budgets that are still predicted as they are (4670 of 4729 runs were measured with no exception to the opener rule); they are checked in the final emulator test of the translation, and the 59 runs that forced drawing did not reach are not chased first. |

## Validation

- Each stage's "done when" is its acceptance test.
- A vertical slice, the intro and the first field area translated and played in MesenCE from a cold boot, proves the chain before the rest of the script is translated.
- The measurements that replace a guess are recorded in [../re/](../re/) or in the entry, with the evidence.

## Risks

- A message built from an address by code nobody found (Blocking Unknown 5): a black screen in one rare scene.
- The factor of 3 to 5 is a guess; if it is higher, the first measurement changes the choice of option.
- A wrong glyph in the table is a wrong word in the source; the confidence field is there so that the review goes first to the doubtful glyphs.
- The skeleton model assumes that a text run is one contiguous run of glyph tokens between commands; blobs with `E8` or `FE` of unknown length may break it until their commands are measured.
