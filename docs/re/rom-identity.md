# ROM Identity

This file records which dump of *Dark Law: Meaning of Death* the translation is built against and how that was verified. Offsets elsewhere in `docs/re/` assume this dump.

## Compatible Original

| Field | Value |
| --- | --- |
| Name | `Dark Law - Meaning of Death (Japan).sfc` |
| Size | 4194304 bytes (4 MiB) |
| Copier header | None: the size is a multiple of 1024 |
| CRC32 | `125A0C22` |
| MD5 | `D58849487D0AB3038F5F9CC38EFC8602` |
| SHA-1 | `A4312636BFAC45A21B3E2F4475E5DB622E9FC0E3` |
| SHA-256 | `6C1749B24124F74D3ACEEFA24297B836B6EE7598FC2094F4D065B3C762C898A4` |

Status: **verified** as the No-Intro dump of the Japanese release. The ROM itself is never stored in this repository; the hashes identify the file a contributor must supply.

## How It Was Verified

CRC32, MD5, SHA-1, and SHA-256 were computed locally over the whole file with Python (`zlib` and `hashlib`), and MesenCE reported the same SHA-1 when loading it (`session.load_rom`, field `fileSha1Hash`). The size, CRC32, MD5, and SHA-1 were then compared with two external records, and all four values match in both:

- The No-Intro entry `Dark Law - Meaning of Death (Japan)`, game identity 0533, as published by the dataset mirror <https://data.spludlow.co.uk/no-intro/> (snapshot labelled 2026-07-28), read on 2026-11-20. This is a third-party mirror of the No-Intro data, not the official Dat-o-Matic.
- The ROM information of the unofficial English translation by Aeon Genesis (version 1.0, 2007-03-28) on ROMhacking.net, <https://www.romhacking.net/translations/307/>, which cites the same dump as `No-Intro 2016-01-12` and states that its patch applies to the headerless ROM. The English patch and this project therefore start from the same dump.

No-Intro does not publish SHA-256, so that value comes only from the local computation.

## Not Yet Verified

The internal SNES header (title, map mode, checksum pair) has not been read or checked in this repository yet. That belongs to the ROM reconnaissance and will be recorded in its own file under `docs/re/`.
