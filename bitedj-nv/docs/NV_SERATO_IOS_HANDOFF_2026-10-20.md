# Numark NV / Serato iOS cross-analysis — continuation handoff
**Saved:** 2026-10-20. **Hardware:** original Numark NV (not NVII), BiteDJ/Mixxx on Pi 4 and NVDJ Android.

**Read this before changing code:** `bitedj-nv/docs/NV_PROTOCOL.md`, `bitedj-nv/CODEX_PROGRESS.md`, `bitedj-nv/NEXT_TASK.md`, and current git status/diff. Preserve the tested v0.5.7 parent-folder-with-children library browser fix, controller behavior and current audio settings. This is documentation only: **no app code changed or hardware tested in this analysis**. User reports Serato DJ for iOS operates their original NV, but this was not independently verified.

## USB captures: established/revalidated, not a newly invented format
Original PCAPs: `numarknvplatter.pcapng` (SHA-256 `9597d4456c326785823af1174c495c6a7a0dc519db6281a450a79022434fd100`) and `numarknvplatterwithaudio.pcapng` (SHA-256 `cac692430f2f0729e730c95061fec6fedcc20eb128cc1ed5514c7be6053b66b5`). Both are VirtualDJ/Windows USBPcap captures. Offline Python decoder reassembled **1,377 + 2,154 = 3,531** `F0 47` LCD SysEx records with zero invalid length fields or seven-bit padding. Other vendor SysEx not starting `F0 47` are intentionally excluded.

```text
F0 47 <10|20> 33 05 <cmd> <outer_hi7> <outer_lo7> <packed_hi7> <packed_lo7> <7-bit data> F7
outer14 = packed14 + 2 ; raw payload repacks the seven-bit stream in little-endian bit order
```

Use physical endpoint identity, not only the `10`/`20` display-family field or transient Windows USB addresses. VID:PID **15e4:1005** main MIDI controls; **15e4:1033** left LCD/audio; **15e4:2033** right LCD. The existing protocol document warns about VirtualDJ tag/routing exceptions. Typical selector mapping: left 0/2 (decks 1/3), right 1/3 (decks 2/4). Command inventory and field byte offsets are already detailed in `NV_PROTOCOL.md`: `01` metadata; `04` BPM/pitch; `05` position/virtual platter; `06/07` overview; `08/09` waveform tiles; `0A` effects text; `21/22/24` browser text; `30` palette. `31` has candidate beat-grid pairs, **not confirmed artwork**. D.VIEW, artwork, RGB pads, master VU LEDs, cue overlays remain incompletely decoded.

### Newly quantified timing evidence
- Audio capture: selector-0 command `05` **1,952** records, **median 15.81 ms** interval (~63/s in active stretches); command `09` **202** records, **median 126.5 ms** interval. This is the cadence of *messages*, not a proof of the NV LCD's physical refresh rate.
- Platter capture: tag-10 command `05` **1,054** records; tag-10 command `09` **103**; tag-20 command `09` **102**.
- `05`: **15 raw bytes / 29 MIDI wire bytes**; layout selector u8, host_clock u32 LE, position i32 LE, platter angle u16 LE, signed speed i32 LE. Normal speed around **1000**, observed min/max **-3324/+3541** in audio recording. These are **host-generated output values, not raw physical jog MIDI**. Source protocol document ties angle to ~1800 ms/rotation at 33⅓ RPM and 1024 angle units.
- `09`: **2170 raw bytes / 2491 wire bytes**, expensive raster/tile data.

## High-priority Mixxx change (DESIGN; NOT IMPLEMENTED)
Published `bitedj-nv/native/numarknvexporter.cpp` calls `timer.start(50)` = 20 Hz on GUI-thread snapshot. `NV_PROTOCOL.md` documents per-display bandwidth **45,000 MIDI bytes/s**, burst 6,000 and 48 queued records. Keep waveform analysis/metadata <=20 Hz or on change, and consider a separate **non-audio** sender for lightweight command-05 updates near 60 Hz using a fresh cached/interpolated transport position/speed/angle. Send fast 29-byte state messages ahead of huge `09` transfers **without interleaving SysEx**, re-render tiles only when needed, drop stale tiles after seek/track changes. Do not increase expensive waveform peak scanning to 60 Hz or block audio. Confirm measurable benefit with filmed NV screen, seek/scratch/reverse/pause/loop and queue/audio stress tests; avoid treating a 15.81-ms capture median as an exact requirement.

## Serato DJ iOS — static evidence, not decrypted algorithms
Extracted valid split archive `SeratoDJ.z01` + `SeratoDJ.zip` -> `SeratoDJ.ipa`, bundle `com.serato.dj`, version **5.0.0 build 5.0.0.1168**, ARM64, minimum iOS 18.6. Main executable + three native frameworks have FairPlay Mach-O `cryptid=1`; analysis did **not** decrypt them or recover actual DSP/model code.

- Readable `SeratoUIViewMetal.metallib` names include `waveform_vertex`, `waveform_fragment`, `playhead_*`, `beatgrid_marker_*`, `cue_*`, textures `intensity_texture` and `frequency_texture`, `WaveformChunkUniforms` and `lowest_decimation`. Practical Android design: cache normalized multiresolution waveform peaks/textures; redraw only dirty chunks, render playhead and overlays separately on GPU. **Does not disclose Serato's waveform-analysis algorithm.**
- `LevelMeterShaders.metallib` metadata: `leftLevelDb`, `rightLevelDb`, `numLEDs`, color parameters. These describe *UI shader* meters, **not NV hardware master VU MIDI**.
- Readable type/name clues: `CoreMLModelRunner`, `AnalyzeStemsOnTrackLoad`, `StemAudioCacheProviders`, `currentStemAudioCacheURIs`, `DeckStemCachesListener`, `DeckCacheStrategyController`, `StemifierController`, `StemFxBehavior`. Shared translation strings mention prepared stems stored on disk. **No verified Serato stem model, file format, caching implementation or speed benchmark extracted**; some shared desktop strings may not apply on iOS.
- Readable names `SmoothEchoController`, `ModDelayEffectsNodeController`, `movePlatter`, `MotorizedPlatterSimulator` are hints only. Do not claim to know Serato's exact scratch or FX DSP.

## High-priority NVDJ Android changes (DESIGN; NOT IMPLEMENTED)
1. Keep audio callback real-time; analyze waveform once per track and store resolution levels. GPU render dirty chunks and overlays independently.
2. Look for the existing `Song.flac.vdjstems` next to the track *first*; reuse without stopping audio. Decouple background model inference from per-deck audio decoders, deduplicate jobs by source/model/quality fingerprint, persist atomically alongside original music, avoid monopolizing CPU cores.
3. Let FX engine keep processing delay/echo buffers with silent input when a deck pauses until the effect tails decay, rather than pausing the FX pipeline.
4. Tune scratch based on actual incoming physical NV jog encoder/touch captures and measured audio response; do **not** derive jog sensitivity from command-05 display telemetry.
5. Preserve already-working USB audio auto-selection and LCD auto-init behavior.

## References, tests and continuation
- Repo: https://github.com/brianbri6/mixxx-NVcontroller
- Protocol: `bitedj-nv/docs/NV_PROTOCOL.md`
- Source: `bitedj-nv/native/numarknvexporter.cpp`
- Baseline verification: `bitedj-nv/scripts/verify_captures.py`, `bitedj-nv/scripts/analyze_lcd_fields.py`
- Tests / build instructions / browser bug preservation: `bitedj-nv/NEXT_TASK.md`
- Other saved local artifacts from this analysis: `NV_Serato_VDJ_cross_analysis.zip` (Python `nv_lcd_capture_decoder.py`, summary JSON, command-05 CSV, full 11-KB report), `SeratoDJ_iOS_Analysis_Report.md`, and `NV_SERATO_IOS_HANDOFF_2026-10-20.md`. These were created in the ChatGPT conversation; the proprietary IPA and music samples are **not** being committed to GitHub.
- Offline decoder (if full toolkit is available): `python3 nv_lcd_capture_decoder.py numarknvplatter.pcapng numarknvplatterwithaudio.pcapng --out findings` -> 3,531 validated LCD messages.

**Continuation prompt:** Inspect current Git working tree/diff, current progress and v0.5.7 browser changes first. Treat command-05 cadence and Serato architecture as engineering leads, not implemented code. Add separate fast LCD transport telemetry without changing waveform cadence or impairing audio, test and commit milestones. For Android, use the latest NVDJ Android source from its own conversation/workspace and prioritize cached GPU waveforms, persistent asynchronous stems and echo tails.
