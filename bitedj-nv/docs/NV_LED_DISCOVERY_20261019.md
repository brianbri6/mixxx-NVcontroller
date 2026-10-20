# Original Numark NV learned MIDI + LED feedback (2026-10-19)

Working branch: `nv-learned-inputs-led-discovery-20261019`. Original NV only, not NVII. Physical hardware acceptance is pending.

## Sources
- User-provided `learned_commands.json`: **142 exact input messages / 98 unique status-address pairs**. The GitHub file `bitedj-nv/controller/NV_learned_commands.json` intentionally contains only raw MIDI keys and user labels (no timestamps).
- User-provided `led test1.pcapng`: **2,994 USB packets / 46.360 seconds**; main controller `15E4:1005` endpoint 01 OUT / 82 IN, with separate `15E4:1033` left LCD+audio and `15E4:2033` right LCD. Main MIDI OUT has **112 distinct status-address combinations**; 84 actively sent by the old feedback code; 28 previously unsupported/requiring review. 130 LCD SysEx frames are not controller LEDs.

## Newly identified output commands
| Hex OUT on controller 15E4:1005 | Physical target | Evidence |
| --- | --- | --- |
| `90 24/25 00/7F` | Channel 1 FX A/B | PCAP switching A off when B on, and vice versa |
| `90 26/27 00/7F` | Channel 2 FX A/B | Same |
| `90 22/23 00/7F` | Channel 3 FX A/B | Same |
| `90 28/29 00/7F` | Channel 4 FX A/B | Same |
| `90 2A/2B 00/7F` | Master FX A/B | Each toggles independently; audio routing not established |
| `90 59/5A 00/7F` | Touch Mode / Filter-Roll LEDs | Observed timed feedback; audio semantics unresolved |
| `91–94 0B 00/7F` | Bleep / Reverse LEDs | Captured but not sent by old JS; newly added feedback |
| `91–94 10/11 00/7F` | Pitch-bend LEDs | Captured but not sent by old JS; newly added feedback |
| `90 12/16 00` | Beat indicators (candidate) | Zero only; lamp-on unverified |
| `B0 47 01` | Beatkeeper far-left LED (owner confirmed) | Position values 00..0B are now mapped |
| `B0 62 02` | Possible host view feedback | Do not infer full LCD view cycle |

The previous unknown-command classification of B0 47 01 is superseded by the user's subsequent hardware test.

MIDI direction matters: e.g. `B0 48` controller IN is a Beat encoder, while `B0 48` OUT is a VU feedback address.

## Beatkeeper protocol decoded — owner hardware confirmation
- `B0 47 00` = entire Beatkeeper row OFF.
- `B0 47 01` through `B0 47 0B` select eleven discrete LEDs from far left through far right. `B0 47 06` is the white center.
- This is a position code, not an LED bitmask or general brightness level. Only 01 was captured in led test1.pcapng; the full 00..0B range was reported as physically verified by the user.
- The user guide specifies center white for matched BPM, with the indicator toward the faster deck.
- Updated JS computes relative BPM between active left and right layer decks, sends OFF when unloaded/invalid, center when within 0.1% (adjustable), otherwise moves by one LED per 0.5% relative difference (adjustable). Cache prevents repetitive identical MIDI commands; refresh interval 200 ms.
- Preset settings: beatkeeperEnabled, beatkeeperMatchPercent, beatkeeperPercentPerStep. These comparison thresholds are software choices, not controller-firmware specifications.

## Mapping changes
- Both JS mapping copies include 142 full-MIDI-value labels, output-feedback method `updateFxAssignmentLEDs`, A/B exclusive FX-unit channel routing, physical Slip input note 04, physical Sel-center note 07, and observational D.VIEW values `B0 61/62 00/01/02`.
- Both XML presets bind an additional **30 missing release/note-off addresses**. All 142 labeled exact messages now have a valid MIDI status+number binding.
- Reverse/Bleep and pitch-bend handlers now send LED feedback from their existing audio actions.
- Master FX, CF contour/start, PFL 0/1/2 switches, Cue Split and touch sensors are **observation only** until functional behavior is tested.
- Optional note LED test `BiteDJNV.testDiscoveredLED(note, on)`, e.g. `BiteDJNV.testDiscoveredLED(0x24,true)`. It refuses unknown CC and never touches USB audio or LCD functions.

## Acceptance
Test (1) all four channel FX A/B pairs against real LED and FX audio routing; (2) master FX A/B LED separately; (3) Touch/Filter-Roll LEDs and possible Beat indicators; (4) Slip, Sel-center and D.VIEW across layers; (5) no unintended audio side effects. No physical test result is claimed yet.

Do **not** merge this working branch to main until those hardware checks pass.

AI-generated v058 correction, 2026-10-20: this is the preserved diagnostic-branch report. See NV_INTEGRATION_V058.md for the subsequent tested source integration. Channel A/B is now independent (manual specifies A and/or B), master routing is implemented, Sel uses normal/Shift mixed-folder navigation, held reverse/bend LEDs clear on layer changes, and CueBlend is single7-bit. Full142 input metadata replaces the labels-only JSON, with LF line endings. Touch/switch/Beat-divisor observations remain available without unverified audio actions. End AI-generated correction.
