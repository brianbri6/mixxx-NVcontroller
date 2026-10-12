# Original Numark NV LCD integration — v0.5.4 development

The user reports partial LCD output on the previous revision. The v0.5.4 renderer is experimental. Offline byte validation establishes record framing and layout, not that an NV will initialize and draw them correctly. The original NV is the target; NVII is not assumed compatible.

## Architecture

BiteDJ's GUI thread reads loaded tracks, numeric deck controls and already analyzed waveforms. A nonblocking local datagram carries the latest snapshot at 20 Hz. A separate Python process renders small indexed bitmaps and writes only to the two identified ALSA raw MIDI outputs. It never opens USB audio, detaches a driver or resets a device. Audio scheduling and the controller mapping remain separate.

HDMI continues to run BiteDJ for library/settings. This is standalone operation without a laptop; HDMI need not be enabled for the LCD data path. A genuinely HDMI-disconnected boot still needs a separate compositor/boot test. The exporter reads analyzer data even when HDMI waveform painting is disabled; availability still depends on BiteDJ having analyzed the loaded track.

## Device identity

| USB VID:PID | Purpose | Driver access |
|---|---|---|
| 15e4:1005 | Main controls | Existing BiteDJ controller mapping |
| 15e4:1033 | Left LCD and USB audio | ALSA raw MIDI output only |
| 15e4:2033 | Right LCD | ALSA raw MIDI output only |

Resolve identity through each `/sys/class/sound/midiC*D*` node's USB ancestors. Do not assume card numbering. Multiple matches are treated as ambiguous.

## Capture evidence

All three recordings are now retained: the two platter captures contain 3,531 display SysEx messages and NumarkNVVDJ.pcapng adds 797, for 4,328 validated records. Hashes are in INPUTS.json. Run `python3 scripts/verify_captures.py` to reproduce framing, counts, platter-angle fits and command 31 inspection; the retained result is `docs/CAPTURE_ANALYSIS.json`.

The focused 2026-10-10 audit additionally decodes FX labels and real browser rows. See [LCD capture report](lcd_capture_analysis/REPORT.md) for all offsets, examples and confidence, and `lcd_capture_analysis/evidence.json` for raw payloads and packet references. Run `python3 scripts/analyze_lcd_fields.py` to reproduce all 4,328 records and exact round-trips of 131 FX/browser text records. v0.5.4 adds live export/rendering for these text fields, using the observed populated and clear byte patterns. Earlier statements that no usable FX/library capture data existed were too broad.

Outer framing is `F0 47 <10 left / 20 right> 33 05 <command> <outer_hi7> <outer_lo7> <packed_hi7> <packed_lo7> <data> F7`. Outer length is packed length plus two. Raw bytes are packed as a little-endian bitstream into seven-bit MIDI bytes. Only a small command/length allowlist is transmitted.

The 10/20 labels are conventions, not a substitute for actual USB routing: VDJ sends its tag-20 palette to the destination otherwise using tag 10. File 04 device 22 is tag 10 and device 21 is tag 20; these transient addresses must not be hardcoded. The audit records USB destination separately from the header tag.

| Command | Raw bytes | Implemented interpretation |
|---|---:|---|
| 01 | 249 | Deck selector; title UTF-16LE 96; artist 96; BPM ASCII 6; key UTF-16LE 42; color 4; duration uint32 LE milliseconds |
| 04 | 19 | Selector; BPM ASCII 7; signed pitch ASCII 7; pitch range ASCII 4 |
| 05 | 15 | Selector uint8 / host clock uint32 / position int32 / platter angle uint16 / signed speed int32; little endian |
| 06 | 7 | Captured overview setup: indexed 240 × 16, eight chunks |
| 07 | 517 | Selector, uint16 chunk number, uint16 valid length, padded 512-byte raster chunk |
| 08 | 7 | Captured detail setup: 30-column tiles, height/cache interpretation provisional |
| 09 | 2170 | Selector, byte 1, uint32 tile time, uint16 1, uint16 2160, indexed 30 × 72 raster |
| 0A | 97 | Screen bank 0/1; three 32-byte ASCII effect labels with optional CR/LF metaknob percent |
| 21 | 131 | Visible folder index; observed populated 06/02 or clear zeros; 128-byte UTF-16LE text |
| 22 | 129 | Observed populated flag 06 or zero clear; 128-byte UTF-16LE heading |
| 24 | 361 | Visible row index; title UTF-16LE 256; artist 96; BPM ASCII 4; observed style ffffffff or zero clear |
| 30 | 1024 | Captured 256-entry BGRA palette |

Overview chunks reconstruct a row-major 240 × 16 image. Detail payloads reconstruct row-major 30 × 72 tiles at 125 ms steps. These are strong structural matches; firmware placement, cache behavior and timing still need a hardware test. Logical deck selectors default to 0/2 on the left and 1/3 on the right and also need confirmation.

Command 05 angle follows a virtual platter at 33 1/3 RPM: 1024 angle units per approximately 1800 ms of track motion, independent of BPM. Continuous-position fits yield 1799.15 ms in the audio capture and 1801.43 ms in VirtualDJ (correlation >0.9999). The short paused-scratch recording covers only 380 ms and is insufficient to estimate a revolution reliably. The v0.5 interpretation as beat phase was wrong; v0.5.1 uses position modulo 1800 ms, including negative pre-roll. Small captured angle/position timing offsets mean this is not a byte-exact model of firmware interpolation. VirtualDJ sends zero host clock/speed; the other captures use a changing host clock and signed speed in units of 0.001x, including paused scratching.

The VirtualDJ capture sends selectors 1/3 to **both** LCDs, while the later capture uses left 0/2 and right 1/3. Preserve the latter routing. The official [VirtualDJ NV setup guide](https://virtualdj.com/manuals/hardware/numark/nv/setup.html) describes separate display assignment and warns that it can be inverted. No new deck-select MIDI addresses are inferred from the misassigned capture.

Command 31 is **not implemented as artwork**. All records fit a selector followed by 256 `(uint32, float32)` pairs. The nonzero pairs contain `(1801, 96.01)` and `(18937, 127.0008)`, matching track BPMs and suggesting a beat-grid structure. The first integer's meaning is unverified; do not invent beat anchors. Artwork, cue overlays and browser status/highlight commands 20/23 remain unimplemented. Captured manufacturer challenge/response traffic and unexplained startup CCs are not replayed; the user now sees partial data, so a missing handshake is not established.

## Modes and limits

- `info`: title, artist, key, BPM, pitch/range, provisional playhead. Captured display setup is still sent.
- `overview`: adds the complete-track colored waveform.
- `full` (default): adds all sixteen provisional scrolling tiles from the native two-second window. An existing BOOT mode file still overrides the default.

Each output is capped at 45,000 MIDI bytes/s, 6,000-byte bursts and 48 queued records. Startup records take priority, then track text/numeric/playhead, FX/browser text, near-playhead detail tiles and remaining waveforms. A partially sent SysEx completes before priority is reconsidered. A tile is acknowledged only after the whole record is written. Expired/dropped records can be retried. Track changes and seeks invalidate obsolete unsent tiles. Reverting a value cancels queued stale data; partially written stale records finish before a corrective record. A partial SysEx finishes without interleaving; a 500 ms partial-write stall closes/reopens the MIDI output. After one second without fresh native snapshots, the renderer labels the data unavailable and stops playhead interpolation. Bounded stale-state retries finish the blank waveform window even if output was initially blocked.

The native exporter is disabled unless BITEDJ_NV_SOCKET is set. BITEDJ_NV_DETAIL=0 skips detailed-waveform export. The renderer does no independent track decoding, file analysis or album-art loading.

## Hardware acceptance checks (not performed here)

1. Confirm audio routing, cue/master output, saved buffer and HDMI waveform setting before and after the update.
2. Install the supplied full-mode file and start with analyzed tracks: load different known tracks on decks 1/2, then switch to 3/4. Check text, BPM, pitch-center indication and deck routing.
3. Check hotplug and restart, then stop the producer and confirm the stale-data warning.
4. Enable overview; compare the displayed full-track outline with the same analyzed track in BiteDJ.
5. Enable full; compare position, speed, pause, seek, scratch, loop and reverse against audio. Film the NV screens with a timestamped action list if anything differs.
6. Run a sustained two-deck audio test and collect the existing F12 diagnostics before considering lower buffers or HDMI waveforms.

No physical hardware pass is implied by software tests or a successful ARM64 build.

## Field coverage and D. VIEW evidence gap

The official [VirtualDJ original-NV control guide](https://virtualdj.com/manuals/hardware/numark/nv/layout/others.html) describes Performance View 1, Performance View 2 and Library View. It describes user behavior, not MIDI addresses. Neither the old Mixxx mapping nor the supplied platter captures identifies the physical D. VIEW button and its matching screen-selection output. The old fork's `B0 64 FF` “maybe” comment is not valid evidence (`FF` is not seven-bit data). Do not reuse it.

| LCD field | Current producer/record | v0.5.4 status |
|---|---|---|
| Title, artist, key, original BPM, duration | Loaded Track / 01 | Implemented |
| Current BPM, pitch percent/range | Native controls / 04 | Implemented |
| Position, virtual platter, signed motion | Native position / 05 | Implemented; timing needs physical check |
| Complete-track colored overview | Analyzed summary / 07 | Eight chunks implemented |
| Scrolling colored waveform | Analyzed waveform / 09 | Sixteen tiles implemented; up to 480 columns |
| Track color | Four bytes in 01 | Left zero; semantics not established |
| Hot-cue positions/colors | Candidate 02/03 | No nonzero cue positions in supplied captures; not implemented |
| Beat-grid anchors | Candidate 31 | Pair structure known; anchor units unconfirmed; not implemented |
| Loop endpoints | Candidate 10 | Only zero/-1 pairs observed; not implemented |
| FX names/two-line labels | 0A: bank + three 32-byte ASCII regions | Live names/metaknob percentage text from FX units 1/2; separate enable and detailed parameter semantics unresolved |
| Folder/header/song-browser text | 21/22/24: UTF-16LE names, ASCII BPM, row index | Live bounded HDMI-model export; captured flags retained; selection uses > text prefix, not guessed status fields |
| D. VIEW / active-view selection | Input not identified; B0 16 is a browser-visibility candidate | Opt-in B0 16 00/01 visibility test; no three-view cycle established |
| Artwork | Unknown | Not implemented |

`nv-status.json` now reports per-deck `overview_ready`, `detail_ready`, the expected detail timestamps, `detail_tiles_sent`, `detail_tiles_pending`, `overview_chunks_sent`, `metadata_sent` and `numeric_sent`. These counters mean completed host writes, not firmware acknowledgements or proof of visible pixels.

At normal position, detail timestamps run from playhead-aligned time minus 750 ms through plus 1125 ms. Each tile covers 125 ms / 30 columns. Negative timestamps are omitted; native analysis provides zeros for missing/out-of-track samples. Loaded-but-unanalyzed decks are explicitly distinguishable in diagnostics. Both layers are retained per screen; initial backfill is slower when both already play because the output budget is unchanged.

The mapping logs unmapped note-on and CC traffic on original-NV channels 0..4, at most 12 messages per address and 600 total per startup. Existing bindings are retained exactly. This observer cannot alter transport or send MIDI. After boot, press D. VIEW left three times and right three times, repeat on layers 3/4, then collect F12. A separate USBPcap recording from working Serato/VirtualDJ should target isolated view presses and nonzero cue/loop changes. Basic FX labels and browser text already have usable layouts; only unresolved parameter/enable and status flags need further evidence. B0 16 changes near track loading/clearing in VDJ and should be checked deliberately; it is not yet an established D. VIEW output.

## Live auxiliary snapshot (v0.5.4)

The native constructor runs after effects setup and PlayerManager/library binding. Library exposes two narrow QPointer-guarded widget accessors; no model is modified. At most every 200 ms the GUI thread reads FX units 1/2, three slots each, and seven active TrackModel rows around its current index. It uses the existing model data roles (EditRole for numeric BPM, locale parsing fallback) and SortColumnId mapping; it never calls getTrack() or scans storage. Missing titles fall back to the model's filename. Up to eight currently visible sidebar entries are read using a bounded indexAbove/indexBelow walk. Non-track views emit no song rows. Widget absence clears browser content.

Schema 1 retains backward compatibility with older producers. Optional `effects` is `[{unit:1|2, slots:[{name,meta_percent}]}]`. Optional `browser` contains `available`, `heading`, `folders` (maximum 8), `selected_folder`, `tracks` (maximum 7 objects with title/artist/bpm), `selected_row`, `first_row` and `total_rows`. Missing BPM is JSON null. Selected indices are local to the transmitted window; -1 means no cursor. Both LCDs mirror the same HDMI selection. FX bank is screen-level, not a deck selector.

Renderer text is packed and cached at at most 5 Hz, with change-only output and retries after queue drops. All eight folders and seven songs are explicitly filled or cleared, including source loss/restart. UTF-16 truncation preserves surrogate pairs; embedded NUL/newline in model text is sanitized. FX text reserves a second CR/LF line for normalized metaknob percent, not an invented device parameter protocol. Selected rows receive a `> ` prefix because status 20/23 semantics are unresolved.

BOOT `BiteDJ_NV_browser_view.txt` / `--browser-view` supports preserve (default, no command), performance (00 on both), left/right (01 on the named side, 00 on the other), or both (01 on both). These use only the observed `B0 16 00/01`; browser visibility is a candidate interpretation. No physical D. VIEW input is bound. Performance explicitly sends zero; preserve/removing the file does not actively reset a prior view.

F12 `screens.<side>.auxiliary` includes effects/browser availability, folder/track counts, selected/first row, visibility-test setting and current desired-field write completion. Completion compares the acknowledged host write to the current desired packet, so an old row does not count as current while an update waits. Continuous browsing can delay waveform backfill under the same rate cap; native/playhead traffic remains higher priority. All visible behavior and 5 Hz model sampling cost still need physical Pi testing.

## Manual behavior reference (2026-10-11)

The supplied original NV User Guide v1.2 confirms Performance 1, Performance 2 and Library views. D. VIEW advances views; Sel opens Library and Load returns to the prior performance view. Shift+D. VIEW changes the host software view. See [NV_MANUAL.md](NV_MANUAL.md), pages 11 and 13–18. This guide supplies no MIDI addresses or packet layouts, so it does not resolve the missing three-view command. It documents no artwork field.
