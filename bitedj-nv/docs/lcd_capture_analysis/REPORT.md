# Numark NV LCD capture analysis

2026-10-10 · Original Numark NV · Offline analysis of the supplied USBPcap files

**There is usable LCD data in these captures.** It includes actual indexed waveform pixels, loaded-track metadata, BPM/pitch/playhead updates and effect labels. The older retained VirtualDJ capture also includes populated folder and song-browser records. Those text fields can be decoded and reproduced; they do not require another capture just to identify their basic layout.

The previous project handoff overstated the missing evidence for FX and library fields. This audit corrects that. It does **not** establish the complete D. VIEW cycle, cue positions, working loop endpoints or artwork. The v0.5.3 Pi update is unchanged; the newly identified fields are implemented in an offline decoder, not yet in the live renderer.

## Which recordings are useful?

| Recording | Duration | Complete LCD messages | Useful contents |
|---|---:|---:|---|
| `03-numarknvplatterwithaudio.pcapng` | 39.739 s | 2,154 | 1,952 motion/playhead updates and 202 nonzero detail-waveform tiles. Starts after setup; no metadata, palette, FX or browser records. |
| `04-numarknvplatter.pcapng` | 63.584 s | 1,377 | Setup, palettes, overview, detail, title/artist/key/BPM/duration, pitch, motion, LPF/DELAY/REVERB labels and a Stems browser heading. Song-browser rows are empty. |
| `05-NumarkNVVDJ.pcapng` — older retained file | 33.562 s | 797 | Track data, both waveforms, dynamic FX text, eight folder rows, browser heading, populated song rows with artists/BPM and selection-related changes. |

All **4,328** complete display SysEx messages decode with consistent lengths and exact seven-bit re-packing. All **131** records for the newly decoded text commands `0A/21/22/24` reproduce their raw bytes exactly, including blank/clear records. Ten manually inspected packet examples also pass explicit expected-value checks.

`evidence.json` contains source hashes, packet references, decoded values, raw low-rate payloads, repeated occurrences, waveform inventory, short MIDI traffic and unlabelled button events. Packet numbers identify the USB packet completing a SysEx, matching the capture frame numbering. Times are relative to the **first USBPcap packet in the file**, not the first MIDI event. Numbers in command/byte notation below are hexadecimal; offsets and lengths are decimal.

## Wire framing and routing

```text
F0 47 TAG 33 05 CMD OUTER_HI7 OUTER_LO7 PACKED_HI7 PACKED_LO7 DATA F7
```

`TAG` is `10` or `20`. `DATA` is a little-endian bitstream packed into seven-bit MIDI bytes. Packed size is `ceil(raw_size × 8 / 7)`; outer size is packed size + 2. Decode that packing before applying any offsets below. A conventional “one high-bit mask per seven bytes” MIDI unpacker is incorrect here.

Do not equate a transient USB device address with a screen. In file 04, device 22 uses tag `10` and device 21 uses `20`. In file 05, device 15 uses `10` except that its palette uses `20`; device 16 uses `20`. The palette exception means even the tag alone is insufficient to prove the physical destination. The JSON preserves the actual bus, device, endpoint, cable and tag. Live routing should continue to use USB identity, not these capture addresses.

Loaded-deck selectors in file 04 follow 0/2 on the tag-10 destination and 1/3 on tag-20. File 05 sends selectors 1/3 to both destinations. Do not use that software-assignment difference to invent a new deck mapping.

## Newly decoded text fields

These offsets and text encodings explain every observed example and permit exact re-encoding. Region widths follow the record size and adjacent fields; the captures do not test the firmware's maximum accepted string length. Strings are NUL-terminated and the remaining region is zero-filled in these samples.

### `0A` — three effect labels, 97 bytes

| Raw offset | Bytes | Meaning supported by capture |
|---:|---:|---|
| 0 | 1 | Bank: 0 on the tag-10 destination, 1 on tag-20. Not the loaded-track selector. |
| 1 | 32 | Effect label 1, single-byte ASCII in these captures |
| 33 | 32 | Effect label 2 |
| 65 | 32 | Effect label 3 |

File 04 packet **2455** contains `LPF`, `DELAY`, `REVERB`. File 05 packet **2091** contains `PITCH\r\n+0`, `STEMS\r\nN/A`, `REVERB\r\n50%`. Packet **3641** changes these to `PITCH\r\nPOS`, `STEMS\r\nVOX`, `REVERB\r\nSTR`. CR/LF therefore occurs inside the label region, carrying two-line text. Non-ASCII encoding and separate numeric parameter/enable controls are not established.

### `21` — folder-list row, 131 bytes

| Raw offset | Bytes | Meaning supported by capture |
|---:|---:|---|
| 0 | 1 | Visible row index 0–7 |
| 1 | 1 | Unknown type/icon/flags; `06` on populated samples |
| 2 | 1 | Unknown depth/flags; `02` on populated samples |
| 3 | 128 | Folder name, UTF-16LE |

File 05 rows read: `freestyle`, `how high`, `Jive`, `Lazerhawk`, `Favorite tracks`, `old house`, `oldnew`, `Rick and Morty`. Packet **2134** starts `04 06 02 46 00 61 00 76 00 …`: row 4, unknown bytes 06/02, then “Favorite tracks”. Both destinations receive the list; later records clear it. The sample does not vary hierarchy depth or icon type, so those bytes retain neutral names.

### `22` — browser heading, 129 bytes

| Raw offset | Bytes | Meaning supported by capture |
|---:|---:|---|
| 0 | 1 | Unknown category/type/flags |
| 1 | 128 | Heading text, UTF-16LE |

File 04 packet **2189**: first byte `08`, heading `Stems`. File 05 packet **1860**: first byte `06`, heading `Favorite tracks`. The 06 also appears in folder rows; its exact semantics remain unproven.

### `24` — song-browser row, 361 bytes

| Raw offset | Bytes | Meaning supported by capture |
|---:|---:|---|
| 0 | 1 | Visible row index 0–6; not a deck selector |
| 1 | 256 | Song title, UTF-16LE |
| 257 | 96 | Artist, UTF-16LE |
| 353 | 4 | BPM text, ASCII; observed integer strings or empty |
| 357 | 4 | Unknown style/color bytes; `ff ff ff ff` in VDJ, zeros in file 04 |

File 04 has **21 blank song rows**, which explains why it alone cannot identify these text fields. File 05 has **34 populated row transmissions**, plus 28 blank initialization/clear records. Its first populated page is:

| Row | Title | Artist | BPM text |
|---:|---|---|---|
| 0 | 18 Plus | Afro Bros | 100 |
| 1 | 18+ (feat. Ghetto Flow) | Afro Bros | 100 |
| 2 | 1942 | G-Eazy | Empty, then 163 |
| 3 | 1M Music | digital music | Empty |
| 4 | 3am | Loe Shimmy | 127 |
| 5 | 530 | Empty | Empty, then 160 |
| 6 | A I O | ANGEL DIOR | Empty, then 120 |

Packet **3339** contains row 4, `3am`, `Loe Shimmy`, `127`. After scrolling, packet **4177** contains the same song at row 3. The next page's last row is **`A+` / `Key Glock` / `127`**, packet **4233**. This movement establishes a visible-row index, not an absolute library ID. Late BPM updates also show that blank means “no BPM text supplied yet”; do not substitute zero. The last four bytes are **not established as an artwork ID**.

## Existing metadata, transport and waveform fields

| Command | Raw bytes | Decoded payload layout |
|---|---:|---|
| `01` | 249 | Selector at 0; title UTF-16LE at 1 (96 bytes); artist at 97 (96); original BPM ASCII at 193 (6); key UTF-16LE at 199 (42); opaque color/style at 241 (4); duration uint32 LE milliseconds at 245 (4). |
| `04` | 19 | Selector at 0; current BPM ASCII at 1 (7); signed pitch percent ASCII at 8 (7); pitch range ASCII at 15 (4). |
| `05` | 15 | Little-endian `<BIiHi>`: selector, host clock ms, signed track position ms, angle, signed speed × 1000. |
| `06` | 7 | Overview setup observed as `01 f0 00 10 00 08 00`: consistent with 240 columns, 16 rows, 8 chunks. |
| `07` | 517 | Selector at 0; uint16 chunk at 1; uint16 valid byte count at 3; 512-byte data region at 5. Chunks 1–7 use 512 bytes, chunk 8 uses 256. Concatenate valid bytes: 240 × 16 indexed raster. |
| `08` | 7 | Detail setup begins `01 1e 00 20 00`; final uint16 is 1 or 2. Width 30 matches tiles; remaining setup/cache meanings are provisional. |
| `09` | 2170 | Selector at 0; byte 1 at 1; uint32 tile time ms at 2; uint16 1 at 6; uint16 2160 at 8; 2160 indexed pixels at 10, reconstructed row-major as 30 × 72. Tiles are spaced 125 ms. |
| `30` | 1024 | 256 four-byte BGRA palette entries. |

File 04 packet **2435** identifies `02 - Encendio - Wisin & Yandel`, artist `www.musicadownloads.net`, **96 BPM**, key **4A**, duration **228,963 ms**. File 05 packet **5159** identifies `3am`, artist `Loe Shimmy`, **127 BPM**, key **Ebm**, duration **136,176 ms**. Earlier VDJ packet 4703 has the title/BPM but no key or duration yet: metadata arrives in stages.

The four-byte field at 241 is `c1 86 00 ff` even on empty decks in file 04; its semantics might be theme/style rather than per-track color. Do not derive artwork from it.

Command 05 angle is consistent with 1024 units per approximately 1,800 ms of track movement, rather than beat phase. The retained `verify_captures.py` checks the long motion fits. VirtualDJ records use zero clock/speed; the other recordings contain clock and signed speed changes. Receiving zero there cannot alone establish whether playback has stopped.

### Extracted waveform evidence

These PNGs render captured indexed pixels with a palette from the **same capture and USB destination**. They are not screen photographs or proposed UI designs. Detail images stitch the last nonzero version of 32 consecutive tiles, track time 0–4 seconds, into a 960 × 72 strip. Overview images use the last complete nonzero eight-chunk set. Source packet lists and pixel hashes are in the JSON. The first capture has no palette, so no colors were invented for it.

File 04 detail:

![Decoded file 04 waveform](04-numarknvplatter-dev22-selector0-detail.png)

File 05 detail:

![Decoded VirtualDJ waveform](05-NumarkNVVDJ-dev15-selector1-detail.png)

There are 621 detail records total: 202/202 nonzero in file 03, 52/205 in file 04 and 214/214 in file 05. Blank tiles are real captured clears/empty data, not a decoder failure. Recognizable waveforms support the raster interpretation; they do not prove firmware positioning, cache lifetime or physical playback timing.

## Partly decoded records and unresolved fields

| Command | Raw bytes | Evidence and limit |
|---|---:|---|
| `02` | 65 | Selector plus 64 bytes. All 12 captured payloads are zero after the selector. A cue-position layout cannot be established from zero-only examples. |
| `03` | 9 | Selector plus eight bytes. Values include 0–7 or 2–9, consistent with cue palette indices. No cue edits to confirm this. |
| `10` | 10 | Selector, flag, then eight bytes. Interpreting the tail as two signed int32s yields only `(-1,-1)` or `(0,0)`. Candidate loop state, but no usable active-loop endpoints. |
| `20` | 10 | VDJ folder status is `04 00 0b 00 00 00 1e 00 00 00`, then zeros at clear. First value 4 matches the Favorite tracks row. `<HII>` gives (4,11,30), but integer widths and offset/count semantics are not established. |
| `23` | 10 | Song status changes from zeros to `00 00 00 00 00 00 ff 00 00 00`, then `03 00 00 00 00 00 ff 00 00 00`. First value 3 matches the scrolled 3am row subsequently loaded. Treat selection as a candidate; the middle value stays zero while the page scrolls, so it is not proven to be a scroll offset. |
| `31` | 2049 | Selector plus 256 `(uint32, float32)` pairs. Nonzero examples (1801,96.010002) and (18937,127.0008) match track BPM in their float portion. Likely beat-grid data; integer anchor units unconfirmed. This is not established artwork. |

No populated album-art payload or image-transfer command was identified. This does not establish whether the firmware could support artwork; it only describes these recordings. Normal waveform pixels must not be mislabelled as album art.

## D. VIEW: a useful lead, not a completed mapping

VDJ sends the following to USB device 15:

| Packet | Capture time | Message/event | Interpretation |
|---:|---:|---|---|
| 827 | 11.783 s | `B0 16 01` | Startup; browser records follow |
| 4703 | 14.825 s | `01` metadata for 3am | Track-load data begins |
| 4993 | 15.009 s | `B0 16 00` | Changes near loading the deck |
| 5159 | 15.166 s | `01` adds key/duration | Loaded-track metadata completed |
| 36770 | 32.123 s | `B0 16 01` | Near the final reset/clear sequence |
| 37409 | 32.242 s | `B0 10 01` | After fields are cleared |

`B0 16` is therefore a **candidate browser-visibility control**. This is correlation with loading/clearing, not proof of a physical D. VIEW press or a three-state view selector. `B0 17` stays 1, so its role cannot be learned from changes. `B0 10` is 0 at startup and 1 around final clearing; the evidence does not show a three-view cycle.

There are unlabelled controller notes, including `90 52` in file 04 and `90 4B`/`90 4C` in file 05. They cannot be assigned to D. VIEW without a recorded action order or known mapping. No input event on the LCD interfaces identifies that button. The old mapping comment suggesting `B0 64 FF` is not valid evidence: FF is not a valid seven-bit CC data value.

## Next implementation and capture work

1. Add live FX-label and browser-row production using the proven text offsets, preserving explicit unknown style/type bytes. This needs BiteDJ data export and bounded update scheduling; offline decoding alone does not populate the live displays.
2. Verify the browser visibility candidate and D. VIEW by recording three isolated presses per side with screen view names or video, keeping a song loaded. Existing v0.5.3 unmapped-input diagnostics can help identify the input, but a working-software USB capture is needed for the matching output.
3. Record a hot cue set and moved to known track times, then an active loop with changed length. The present zero/sentinel records are insufficient for those coordinates.
4. If working software visibly displays artwork on this original NV, capture loading two tracks with different art and film the screens. No usable art data was found here.

There is no need to repeat ordinary title, BPM, FX-name or library-row capture just to recover their basic text layouts. A future capture should target the unresolved changes above and FX numeric/enable controls if those are to be implemented.

## Reproduce the analysis

Python 3.9+; standard library only. Run from the recovered project root, with the three original PCAPs at their pinned `project_sources/` paths:

```sh
python3 scripts/analyze_lcd_fields.py
python3 scripts/verify_captures.py
git diff --check
```

To generate a separate result directory, use `python3 scripts/analyze_lcd_fields.py --output work/lcd-audit`. No Pi build, MIDI port, USB replay, audio playback or network access is used. The standalone analysis ZIP includes the decoder, capture parser and commands; provide the original PCAPs locally as listed below. The full recovery checkpoint retains those captures and Git history.

| Source | SHA-256 |
|---|---|
| 03-numarknvplatterwithaudio.pcapng | `cac692430f2f0729e730c95061fec6fedcc20eb128cc1ed5514c7be6053b66b5` |
| 04-numarknvplatter.pcapng | `9597d4456c326785823af1174c495c6a7a0dc519db6281a450a79022434fd100` |
| 05-NumarkNVVDJ.pcapng | `f7ef49c90e1ae023643a16555ed3d30ad7e1ea9f15dd65d5abd421525587cb6c` |
