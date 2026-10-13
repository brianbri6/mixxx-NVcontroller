# BiteDJ Pi4 + original Numark NV — experimental v0.5.7

Standalone Raspberry Pi4 4GB: HDMI for music selection/settings, NV LCDs for track information, BPM and experimental waveforms. This is a **reversible update for the saved Pi4 HDMI NV v0.3 image**, including installations already updated to v0.4, v0.5, v0.5.1, v0.5.2, v0.5.3, v0.5.4 or v0.5.5. It is not a complete SD image, an NVII update, or an updater for stock Deckshark.

**v0.5.7 fixes opening folders that contain both songs and subfolders.** Select a folder's label to show its own songs; use its expansion arrow to see subfolders. The NV LCD mirrors the active HDMI list. Shift + the mapped navigation button expands/collapses the selected folder, while a normal press opens its songs. Physical Pi/NV acceptance is still required. The v0.5.6 FX, pad and master-meter controls and working v0.5.5 SD music helper are retained. D. VIEW cycling and all LCD fields are not yet complete.

## What changed

- FX: three buttons and knobs per side control three effects in FX units 1/2. Button LEDs follow the software. See the control table below for wet/dry and effect selection.
- Pads: assigned cues, loops, rolls and loaded samplers receive configurable captured palette codes, with blinking for active states. The exact visible colors need a photo from the NV; arbitrary RGB values are not supported yet.
- Master meters: sends separate left/right post-gain VU levels to captured CC48/49 destinations, including silence clearing and the startup lamp test. Physical destination and red segment still need verification.
- Browser: navigation now enters a sidebar item or returns to folders, and the encoder moves the focused list. Optional right-LCD browser setup is described below; automatic D. VIEW switching remains unresolved.
- Retains the working SD MUSIC mount helper, F12 diagnostics and a separate reversible v057 runtime/journal, including rollback to v056.

Retained from v0.5.4:

- Live FX text: actual names and normalized metaknob percentages for three slots in standard FX unit 1 on the left LCD and unit 2 on the right. These are text labels; independent FX enable indicators and detailed parameter names are not mapped.
- Live browser text: both LCDs receive the active HDMI table's title, artist and BPM for seven tracks around the current cursor, plus up to eight visible sidebar entries and the current heading. A `> ` text prefix marks selection. Unknown BPM remains blank and fills in when the model receives it. Old rows clear when the list shrinks or the producer stops.
- FX/browser sampling is limited to 5 Hz. It reads the existing GUI models without opening tracks or scanning directories. Playhead and track fields retain priority above browser traffic; the 45 kB/s output cap and partial-packet protection remain.
- An optional browser visibility experiment uses only the captured `B0 16 00/01` values. The default sends no new view command. It is **not** a verified D. VIEW cycle.
- All sixteen scrolling waveform tiles, overview, VU idle/fader clearing, adjustable scratch response, layer/pitch fixes, port ownership and F12 diagnostics from v0.5.3 are retained. The earlier controller functions remain covered by regression tests.

This revision requires a fresh ARM64 application build for the native sidebar fix. Native exporter, audio engine and scheduling source are unchanged. Folder scanning still lists direct files; child songs are not merged into the parent list.

## Install

1. Shut down the Pi, insert its SD card in your computer, and back up BOOT's existing `initramfs.img`, `BiteDJ_NV_display_mode.txt` and `BiteDJ_NV_browser_view.txt` / `BiteDJ_SD_music.txt` (if present) to your computer.
2. Extract `BiteDJ_Pi4_NV_Display_Test_v0_5_7.zip`. Copy **`install/initramfs.img`** directly onto BOOT, replacing the backed-up file. Keep your existing display mode. If you also want to enable full NV waveforms, optionally copy `install/BiteDJ_NV_display_mode.txt` to BOOT; it contains `full`.
3. For easy tuning, also copy **`settings/BiteDJ_NV_settings.json`** directly onto BOOT. This is optional: without it, the new mapping defaults to 2× scratch response. Preserve any settings file you previously customized.
4. Keep `config.txt`, `cmdline.txt`, audio routing and HDMI waveform settings unchanged. Keep HDMI waveforms disabled as in the smooth Pi4 setup. Safely eject and boot with the NV powered and connected.
5. If installation is skipped, read **`BiteDJ_NV_v057_update.txt`** on BOOT. Unrecognized/customized program or mapping files are not overwritten. An interrupted older update must recover using its own saved updater before upgrading.

The new slot is `/usr/local/lib/bitedj-nv-v057/`. The original application, previous version slots and previous backup journals stay intact. Startup disables only `[Controller]` NV Audio/Graphics enable flags that reference this NV controls mapping. In HDMI **Devices**, leave those two MIDI rows disabled and NV Control enabled. **Do not disable NV Audio in the audio-output settings.**

## SD music partition

The inspected images mount BOOT and the OS partition, while their automatic media rule handles USB drives only. Also, PID1 later puts a tmpfs over `/media`, which can hide an earlier mount made there. This is the leading explanation for the missing SD music. The user confirmed v0.5.5 restores music browsing; no current partition report was supplied to establish the exact earlier failure.

On the supported layout (ext4 OS on MMC partition 2), the retained v0.5.5 helper looks for exactly one extra partition on that same card labelled `MUSIC` (case-insensitive). It accepts exFAT, FAT or ext4. It does not choose BOOT/root, USB drives, a different card or an unlabelled partition. It does not format, repartition, run filesystem repair, change track paths or rescan the library database.

After boot, open **Computer → Removable Devices → MUSIC** in the HDMI browser. The new mount path is `/media/MUSIC`. If another startup component already mounted this partition, its existing path and read-only state are retained instead. A custom path outside the browser's removable-device roots can still need separate attention; F12 records that path. Saved playlists using a different old path are not automatically migrated.

`BiteDJ_SD_music.txt` on BOOT accepts `auto` (default if absent) or `off`. Examples are in `sd-music-examples/`. `off` skips this helper on the next boot; it does not unmount an existing filesystem or disable other mounting components. Keep any previously customized BOOT file unless intentionally changing it.

If the music still does not appear, press **F12** and send the new diagnostics ZIP from BOOT. `sd-music-status.json` distinguishes a missing label, unsupported layout/filesystem, existing mount, blocked destination and a mount failure. `sd-music.log`, partition information and mountinfo provide the details. Do not reformat the partition to troubleshoot this release.

## Adjust scratching and LEDs

Edit **`BiteDJ_NV_settings.json` on BOOT**, then restart the Pi. For example, change `"scratchSensitivity": 2.0` to `4.0` for twice the new default response. Start at 2, increase to 3 or 4 if movement still feels weak, or return to 1 for the previous response.

| Setting | Default | Meaning |
|---|---:|---|
| `scratchSensitivity` | `2.0` | Rotation multiplier, 0.25–8; larger means more track movement |
| `jogSensitivity` | `0.25` | Untouched platter pitch bend, 0.05–2; independent of scratching |
| `vuFollowFader` | `true` | Dark at fader bottom, estimated post-fader bars; `false` selects pre-fader meters |
| `vuSilenceThreshold` | `0.01` | Normalized meter floor, 0.0002–0.1; removes tiny decaying residuals |
| `vuPeakLevel` | `5` | Candidate red-segment MIDI value; use 4 to limit output to the captured range |
| `vuTest` | `false` | Set `true` for the seven-second channel and master lamp test |
| `padColor1` … `padColor8` | `12,52,48,21,6,3,52,21` | Per-pad palette codes: only `0,3,6,12,21,48,52`; `0` keeps that pad dark |

The complete example is valid JSON; keep quotes, commas, and lowercase `true`/`false`. Unknown keys or invalid values reject the document without applying its tuning or port changes. BiteDJ still starts with prior saved preferences. F12 exports the error in `nv-settings-status.json`.

The native Mixxx mapping-settings API stores these values. The current BiteDJ HDMI Devices screen does not expose its tuning widgets, so use the BOOT file in this revision. Removing the file keeps its last applied values. To reset, copy the default example or perform full rollback.

For the red LED test, use `"vuTest": true` or the supplied `settings/lamp-test/` example. Watch all four channel meters and both master strips count upward and return to normal VU. Report which value reaches red; **there is no need to raise speaker volume**. Change `vuTest` back to `false` afterward. In normal use, red represents the engine's clipping flag while the fader is open, not merely the fader's position. The post-fader bars are a visual estimate; clipped or smoothed samples cannot be reconstructed.

## FX and pad controls

| Control | Action |
|---|---|
| Left FX buttons 1–3 | Toggle slots 1–3 in FX unit 1 |
| Right FX buttons 1–3 | Toggle slots 1–3 in FX unit 2 |
| FX knob 1–3 | Adjust that slot's metaknob (combined effect parameter) |
| Shift + FX button | Select the next effect in that slot |
| Shift + first FX knob | Adjust that side's FX unit wet/dry mix |

An empty slot loads an available effect when pressed. If FX is inaudible, raise its wet/dry using **Shift + the first FX knob**; enabling a slot preserves the existing wet/dry setting. Turning a unit on routes it to the last deck observed on that side. Initially this defaults to decks 1/2: after selecting 3/4, touch a mapped deck control before enabling FX. Existing routes to other decks remain; use HDMI FX routing to remove those if desired. Dedicated hardware FX assignment buttons and single-effect parameter pages are not mapped yet.

Cue mode colors assigned hot cues; empty cues are dark. Loop/roll mode colors available pads when a track is loaded; active loops/held rolls blink. Sampler mode colors loaded samplers and blinks during playback. Slicer remains disabled. Colors are per pad number across modes/decks and use the captured codes listed above; they do not yet track custom cue colors from the software.

Master meters follow the software **Main** signal after gain/balance/talkover, without applying channel faders a second time. Changes occurring in the NV's analog hardware may not appear in those software meters. In F12, look for `BiteDJNV master meters [vu,peak,led] left/right`. Verify silent zero and the lamp sequence before evaluating the response while playing.

## LCD modes and hardware check

BOOT's **`BiteDJ_NV_display_mode.txt`** contains one word:

| Mode | Behavior |
|---|---|
| `info` | Title/artist/key, BPM, pitch/range and provisional playhead; no waveforms |
| `overview` | Adds a complete-track colored waveform |
| `full` | Default: overview plus all 16 provisional scrolling tiles |
| `off` | Original application, no LCD service; keeps this revision's mapping/tuning |

Load analyzed tracks on decks 1/2, keeping HDMI waveforms disabled. Allow the initial waveform window to fill before evaluating scrolling, then check decks 3/4. F12 `nv-status.json` distinguishes missing analysis from pending or sent tiles. Initial backfill is slower when both layers on one screen are already playing. `info` and `overview` remain available as fallbacks.

The supplied NV manual confirms Performance 1, Performance 2 and Library views, with D. VIEW advancing views and Sel opening Library. It provides no MIDI commands. See [manual findings](docs/NV_MANUAL.md) for the intended behavior and remaining evidence. The documented views do not include album artwork.

**D. VIEW still needs identification.** After a fresh boot, press left D. VIEW three times, wait a few seconds, then right D. VIEW three times. Repeat on layers 3/4, then press **F12** and send the diagnostics ZIP. Also note which view appears, if any. Unmapped events are logged as `BiteDJNV unmapped MIDI`. They intentionally cause no action until identified.

To identify the outgoing view and remaining fields, a short USBPcap recording with working Serato/VirtualDJ is also needed: show three D. VIEW presses on each side, set/move a hot cue, change loop length and FX numeric/enable controls. Include a brief action order or screen video. Existing captures contain no identified D. VIEW sequence and no nonzero cue positions. The 2026-10-10 audit **does** recover populated FX labels and browser text from the retained files, so their basic layouts do not require another capture.

For the remaining green LED, pause both decks, wait two seconds, put all four channel faders fully down, and press F12. Then run the optional lamp test and report whether **value 0** goes completely dark and whether **value 5** reaches red. There is no need to turn up speakers. A photo/video should identify the affected strip. Diagnostics record `[vu,fader,peak,led,idle]`; an output of zero with a lit lamp points to hardware encoding/ownership rather than a VU floor.

Song title, artist, key, original/current BPM, pitch/range, duration/playhead, both waveform forms, FX text and browser rows are implemented. **D. VIEW cycling, hot-cue/loop overlays, detailed FX parameter/enable indicators and artwork remain unimplemented.** See `source/project/docs/NV_PROTOCOL.md` for field coverage and evidence. Full mode does not invent values for unsupported fields.

The subsequent [LCD capture analysis](docs/lcd_capture_analysis/REPORT.md) identifies offline layouts for FX labels (`0A`), folders (`21`), browser headings (`22`) and song rows (`24`), with title/artist/BPM and actual waveform PNGs. All 131 new text records round-trip exactly within 4,328 validated LCD messages. `B0 16` is a candidate browser-visibility control, not a proven D. VIEW cycle. v0.5.4 integrates the populated text layouts. The previously released v0.5.3 ZIP is retained unchanged.

## Browse music on the NV LCDs

First install with the default view behavior, load tracks and check waveform/FX fields. To test the captured browser-visibility candidate, copy **`browser-view-examples/right/BiteDJ_NV_browser_view.txt`** onto BOOT and reboot. This requests performance mode on the left and browser mode on the right. Move the HDMI library cursor, scroll, change a folder and wait for analyzed BPM; compare the right LCD with HDMI. Both LCDs receive the same library page even when a performance view hides it.

With the library active, turn the browse encoder to move selection. The mapped navigation/Fwd button (deck MIDI note 06) returns from tracks to folders; in folders it opens the selected directory’s own tracks, even if that directory has subfolders. Shift + that button expands/collapses the folder tree when focused there; from tracks it returns to folders. Open a folder to focus its tracks, then use the existing deck Load button. The LCD mirrors the active HDMI model, including filesystem music folders. It is a bounded page around the cursor, not an independent second browser. Check that the physical button is Fwd on your NV; the Sel push and automatic return-to-performance still need labelled input evidence.

| File value | Request sent to the LCDs |
|---|---|
| `preserve` | Default; no visibility command sent |
| `performance` | Captured value 0 to both screens |
| `left` | Value 1 left, 0 right |
| `right` | Value 0 left, 1 right |
| `both` | Value 1 to both screens |

This is a hardware experiment: value 1 correlates with browsing in the capture, but the actual NV view must be observed. To request a return to performance, use `performance` and reboot; `preserve` or removing the file only stops issuing the command and does not actively reset the display. Collect F12 and a photo if the view differs. The file accepts one listed word, not arbitrary MIDI or commands.

F12 auxiliary status reports source availability, row counts/current cursor and write completion. “Sent” means the host completed its MIDI write, not a firmware acknowledgement. Continuous fast scrolling shares the existing bandwidth and may delay waveform backfill; playhead traffic keeps priority.

## Rollback

For an immediate LCD fallback, select `off` and reboot. This keeps the new controls mapping and preferences.

For **full v0.5.7 rollback**, copy the empty **`rollback/BiteDJ_NV_v057_rollback`** file onto BOOT and reboot **with the v0.5.7 initramfs still installed**. Check `BiteDJ_NV_v057_update.txt`. The updater restores the previous launcher, diagnostics, mapping and owned NV preference values, and removes the v0.5.7 runtime files. It leaves later unrelated settings changes intact; it also keeps an owned setting you changed after the update instead of overwriting it.

Keep the rollback marker to prevent reinstalling, or restore the exact initramfs you backed up. Restore your previous mode file too if you copied the full-mode test file, and restore/remove the optional browser-view and SD music files. When rolling back before v0.5.5, the SD helper no longer runs; it does not unmount a partition during an active session. Those BOOT files remain user-owned. Rollback returns to the version you upgraded from: v0.5.5, v0.5.4, v0.5.3, v0.5.2, v0.5.1, v0.5, or the original v0.3/v0.4 app. To undo earlier versions too, use each saved version's initramfs and its own rollback marker in reverse order. Do not install an older updater over an active newer version before rolling the newer version back. Edited program/mapping files block rollback rather than being overwritten; retain the report if this happens.

## Validation and remaining work

- **26 controller and 69 Python tests pass**, including captured text/clear records, Unicode/size bounds, cursor changes, late BPM, list shrink, stale/restart retry, waveform coverage and scheduling under rapid browser changes. Fourteen SD-specific tests cover mount guards, timeouts, existing paths and startup in all display modes. The original VU/scratch tests remain passing.
- The unchanged ARM64 binary retains its matching 127-file runtime dependency audit and QEMU --version evidence. All 37 actual-payload install/idempotence/rollback scenarios pass, including v0.5.5 upgrades, protected SD settings and simulated interruption recovery. All 990 unrelated initramfs members are preserved; shell and FAT checks pass.
- All **4,328** recorded LCD messages validate. Basic FX/browser layouts are usable. Track color, beat anchors, cue/loop coordinates, D. VIEW cycling and artwork remain unresolved.
- The user reports partial LCD output on the earlier revision. VU zero/off and red value 5 still require physical observation; the silent lamp test avoids raising speaker volume.
- Local AF_UNIX testing is restricted. No GUI, live FX/browser export, USB LCD, sustained audio or HDMI-disconnected boot pass is claimed. Prior GUI emulation was inconclusive for both baseline and rebuilt apps; version checking is a much narrower test.

## Rebuild and continue

Read `CODEX_PROGRESS.md` and `NEXT_TASK.md`. The checkpoint retains Git history and all three captures. Restore the v0.3 image and v0.5/v0.5.1/v0.5.2/v0.5.3/v0.5.4/v0.5.5/v0.5.6 ZIPs to their pinned `baseline/` paths in INPUTS.json. On Linux with Python 3, `zstandard`, Node.js and `debugfs`:

```sh
# Skip extraction/checkout/toolchain setup if those exact inputs already exist.
python3 scripts/extract_image.py baseline/BiteDJ_Pi4_4GB_HDMI_NV_Test_v0_3.zip --output work/base
mkdir -p work/rootfs
debugfs -R 'rdump / work/rootfs' work/base/root.img
git clone --filter=blob:none --no-checkout https://github.com/TeamDeckshark/bitedj.git vendor/bitedj
git -C vendor/bitedj checkout 78074e05c8bf99ede6fedd755aa68bd222ba343c
# If the checkpoint contains a matching native binary, apply and verify instead:
python3 scripts/apply_native.py
PYTHONPATH=scripts python3 -c 'from native_build_evidence import verify; print(verify("work/build-arm/mixxx"))'
# Only if matching native artifacts are missing or native source changed:
python3 scripts/prepare_toolchain.py > work/toolchain-v057.log 2>&1
sh scripts/build_arm.sh > work/build-arm-v057.log 2>&1
python3 scripts/audit_arm.py
python3 scripts/check_native_version.py
# Runtime/package checks after the fresh native build:
node tests/test_controller.js > work/test-controller-v057.log 2>&1
python3 -m unittest discover -s tests -v > work/test-v057.log 2>&1
python3 scripts/verify_captures.py
python3 scripts/analyze_control_feedback.py
sh -n runtime/launch.sh
python3 scripts/build_update.py --native-binary work/build-arm/mixxx > work/test-package-v057.log 2>&1
git diff --check
# Commit all source/docs before packaging. Never overwrite an existing release.
python3 scripts/package_release.py
python3 scripts/checkpoint.py --with-native-build --with-package
```

The build uses the hash-verified libkeyfinder source from v0.5, supporting offline dependency builds. `native-build.json` binds the executable to the applied source hashes; packaging rejects stale evidence, incompatible runtime libraries and changed payload sources. Dependency manifests are retained with the validation evidence. When source evidence matches the pinned v0.5.4 release, the updater builder copies that exact stripped executable, so no cross-toolchain is needed for this JS/Python controls update.

`python3 scripts/smoke_arm.py` can test native datagrams on a permitted host; do not bypass this environment's Unix-socket restriction. Preserve the appliance's real-time settings and bounded display queue. Native changes use GPL-2.0-or-later; Python integration uses MIT. The package includes source, patch, dependency source, attribution and licenses.
