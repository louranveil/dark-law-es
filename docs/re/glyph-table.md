# Glyph Table

Status: **verified by reading** for the 920 glyphs that the dialogue uses, with 4 readings still open (see Open Items). This is a human-style reading of the font, not a proof: a glyph is `seen` when its shape was read on an enlarged sheet and the character made sense in the messages that use it. Claims follow the convention of [text-engine.md](text-engine.md).

The table is `tbl/original.json`; the tools are `tools/glyph_font.py` (reads the font from the ROM and draws the sheets) and `tools/glyph_table.py` (loads, validates and applies the table). The glyph storage is in [font.md](font.md).

## What Is In The Table

- 920 glyph keys, all the glyphs that the 2797 message blobs of the area tables and the called-scripts table use: 180 single-byte codes (key `0A`) and 740 kanji (key `FD 3A`: page prefix and index).
- 907 are text (kana, kanji and a few signs), 5 are large Latin letters (`M P K O L`, used for `HP`-style labels), 4 are icons, 2 are blanks and 2 are placeholders (a box with a diagonal).
- Each entry has `char`, `kind`, `confidence` and an optional `note`. The format and the rules are in the header of `tools/glyph_table.py`; `tests/test_glyph_table.py` checks the file against them.

## Layout Of The Single-Byte Page

Measured on the sheets, in the order of the Japanese syllabary (gojūon). Every used code was seen on a sheet.

| Codes | Content |
| --- | --- |
| `00` | blank (space) |
| `01`-`2E` | hiragana あ い う え お か ... わ を ん (46 syllables) |
| `2F` | ー (long vowel mark) |
| `30`-`3F` | voiced hiragana が ぎ ぐ げ ご ざ じ ず ぜ ぞ だ ぢ づ で ど ば |
| `40` | placeholder: a box with a diagonal (see Open Items) |
| `41`-`6E` | katakana ア イ ... ワ ヲ ン (46 syllables) |
| `6F` | ヴ |
| `70`-`7F` | voiced katakana ガ ギ ... ド バ |
| `80`-`88` | びぶべぼ and ぱぴぷぺぽ |
| `89`-`8D` | small ぁ ぃ ぅ ぇ ぉ |
| `8E` `8F` | ？ ！ |
| `90`-`98` | ビブベボ and パピプペポ |
| `99`-`9D` | small ァ ィ ゥ ェ ォ |
| `9E` `9F` | ・ 、 |
| `A0`-`A7` | small っ ゃ ゅ ょ ッ ャ ュ ョ |
| `A8`-`B1` | full-width digits ０-９ |
| `B2` | a mark of two ticks (see Open Items) |
| `B6` | ＆ |
| `B8` `B9` | the red and white cursor triangles |
| `BD` | placeholder |

The codes `B3`-`B5`, `B7`, `BA`-`BC`, `BE` and `BF` hold other drawings (a slash, a plus, a minus bar, a red icon, a large `M`) or the box with a diagonal; no message uses them.

The kanji pages hold the glyphs in the order in which the original developers added them, with no obvious sorting (the first rows of page `FD` are 聖 霊 力 ... ). The glyph of each kanji was read from the sheet, not derived.

## How It Was Made

1. `glyph_font.py --rom ... --out ...` counts the glyphs that the messages use and draws sheets of 50 glyphs at 4x, single-byte codes first and then kanji, from most to least frequent, each with its key and its count. All 920 glyphs were read this way.
2. The kana were read as a block, and the order above was confirmed against every used code on the sheets. The kanji were read from the shapes, most of them at 4x and the doubtful ones at 7x.
3. Every kanji was then looked up in the text: the table prints two contexts of each glyph (three characters before and after) and the nonsense words were fixed. This step corrected about forty readings of the first pass, all of them confusions between similar shapes. Examples: 矢 and 失 (`矢を放つ`, `失われて`), 達 and 違 (`君達`, `間違えた`), 穴 and 窟 (`洞穴`, `洞窟`), 鋭 and 鏡 (`鋭い爪`), 界 and 累 (`世界`), 木 and 末 (`木の間`, `断末魔`), 疲 and 渡 (`疲れが癒`, `渡しました`), 奇 and 寄 (`奇妙`, `寄生`), 利 and 刹 (`勝利`), 礼 and 札 (`失礼`), 教 and 数 (`大司教`, `数日`), 璧 and 壁 (`完璧`, `岩壁`).
4. The table decodes real messages. The intro of the new game (`tools/glyph_table.py show --blob E2EE73/0`) reads `300年前・・・ この世界の大地には ふたつの国が存在した ... レイフォール王国 ... アムグノン王国 ...`, and the following messages read as ordinary Japanese.

## What This Does Not Prove

- A reading that makes sense in two contexts can still be a similar kanji. The check is as strong as the contexts are many: frequent glyphs were seen in many messages, glyphs with one use (106 of the 740 kanji) were read on the sheet and in that one context, and 171 kanji have at most two uses.
- No dictionary was used. A second reader who knows Japanese should go through `tbl/original.json` (the file has one glyph per line) and the sheets, giving priority to the glyphs with the fewest uses (the sheets list them last).
- The counts in the sheets include arguments of commands that the tokenizer does not know the length of (`FE`, `E8`) and reads as text; this is why the placeholder `40` shows 76 uses. See [text-engine.md](text-engine.md).
- Aeon Genesis's English patch was not consulted, which keeps the Japanese as the source. It can settle some of the open readings.

## Open Items

1. `40` and `BD` (box with a diagonal): the glyph the font draws when a code has no picture. The uses of `40` that were looked at are command arguments, not text. `BD` has one use. Decide, with the arity of the `FE` and `E8` commands, whether they appear in the text at all.
2. `B2` (two ticks): follows `・` and the start of a page and precedes page breaks. It reads as a quotation mark or a decorative mark; its table character `”` is a placeholder until a decision is taken. It is used 227 times, so it matters for the layout of the Spanish text.
3. `FB 4C` (`災`, `この地の災と闇を`): the shape is not settled; the context fits `災`.
4. `FA 66` (a small red and white cross, used after text such as `本当に`) and `FB 97` (a bar with red ends): icons with no character; their role (punctuation or gauge) is unknown.
5. A second reader for the glyphs with one or two uses.
6. A detail for the translation: `FB A2` appears in `堀当てま`, probably a slip for `掘り当てました`; it is kept as read.
