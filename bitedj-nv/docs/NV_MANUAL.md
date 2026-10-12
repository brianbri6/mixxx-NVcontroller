# Original Numark NV display requirements

Source: the user's `project_sources/05-NV-UserGuide-v1.2.pdf`, unchanged, SHA-256
`8f25871309baf60a1860bc1bcff05da38161ffc5fba29a7a931d65dc8808a7b6`.
Page numbers below are both printed and PDF page numbers. Relevant pages were
text-extracted; pages 13 and 14 were also rendered and visually checked.

## Behavior confirmed by the manual

| Control or view | Requirement | Page |
|---|---|---:|
| D. VIEW | Advance among Performance View 1, Performance View 2, Library View | 11, 13 |
| Shift + D. VIEW (S. VIEW) | Change the host software's display mode | 11 |
| Sel knob rotation | Enter Library immediately and move through tracks | 13, 18 |
| Load in Library | Load to the selected deck and return to the previous performance view | 13, 18 |
| D. VIEW in Library | Leave Library for the prior view, per the manual's return instructions | 13 |
| Sel press / Back-Fwd | Move between track and crate lists; Back-Fwd expands/collapses crates | 11, 18 |
| Deck button | Left selects layer 1/3; right selects 2/4 | 14, 16 |

The manual describes three available views and a next-view action, but does not
fully disambiguate all cycle/return transitions after automatic Library entry.
Record the starting view and each resulting view when capturing the buttons.
Library View does not show the current deck, so confirm the selected layer before
loading (page 18).

## Field coverage

| Manual view | Documented fields | Current integration |
|---|---|---|
| Performance 1 (pp. 14–15) | Deck, title, artist, original BPM/key, current BPM, remaining time, pitch/range, track overview, auto-loop choices, FX names/parameters/beats multiplier | Track/numeric/overview data and FX text implemented; loop, parameter indicators and beats multiplier incomplete |
| Performance 2 (pp. 16–17) | Deck, scrolling title, original BPM/key, current BPM, remaining time, pitch/range, overview and scrolling waveform, loop length, FX names/parameters/beats multiplier | Track/numeric and both waveforms implemented; FX text implemented; remaining indicators incomplete |
| Library (p. 18) | Crate/list heading and rows containing title, artist, BPM | Heading, eight folder rows and seven song rows exported from HDMI; text prefix marks selection while native highlight flags remain unknown |

The depicted performance views show hot-cue and loop overlays; the retained USB
captures contain no usable nonzero cue positions or active loop endpoints. The
manual names the fields but does not establish their packet encodings. Likewise,
text percentages are a deliberate current representation of the Mixxx metaknobs,
not a claim that the native FX knob graphics/enable indicators are mapped.

The documented views do not list or depict album artwork. Artwork remains a user
goal, but neither this guide nor the supplied captures demonstrates how the
original NV firmware accepts it. Do not label command 0x31 as artwork or promise
an artwork field from these sources.

## Evidence still needed

The guide contains no USB/MIDI command table. It does **not** identify the input
note/CC for D. VIEW, the three-view output command, highlight flags, or overlay
coordinates. The existing `B0 16 00/01` browser experiment must remain separate
from a verified three-view mapping.

Use a brief working Serato/VirtualDJ USBPcap with an action log/video: start in
Performance 1, press D. VIEW three times on the left and then right; enter Library
with Sel and load a track; repeat after selecting layers 3/4. Include a moved
hot cue and changed active loop. On the Pi, F12 after the same button sequence
can identify observed input events, but cannot establish output commands by
itself. Do not guess addresses from unlabelled presses.
