# NV controls evidence and v0.5.6 hardware checklist

The original NV reference is pinned to manzyun/mixxx revision `6e999daaf62322e351169b364f071dfb1df4e4c1` in `reference/nv/`, with INPUTS.json hashes. It identifies the FX address banks but its behavior is not copied: some FX handlers/keys are broken and the duplicated last right button contains a channel typo. The consistent global bank and captured LED output support the global channel used here.

`python3 scripts/analyze_control_feedback.py` regenerates `docs/control-feedback-evidence.json` from hash-pinned PCAPs. USB Control endpoint 1, cable 0 is selected explicitly; Audio/Graphics traffic is excluded. Each record includes direction, packet examples and value counts. No capture is replayed.

| Feature | MIDI (hex) | Evidence / remaining uncertainty |
|---|---|---|
| Left FX buttons | 90 0F/10/11; releases 80 or velocity 0 | Original mapping; output initialized off in capture |
| Right FX buttons | 90 13/14/15; releases 80 or velocity 0 | Original mapping consistent bank; last-note typo reviewed |
| FX knobs | B0 04/05/06 and 49/4A/4B | Original mapping, absolute 0–127 |
| Pad output, decks 1–4 | 91–94 47–4E | Captured note addresses; palette codes 0,3,6,12,21,48,52 |
| Master stereo candidates | B0 48/49 output | Independently varying captured streams during audio; physical master label inferred |
| Folder navigation | 91–94 06 input | Existing original mapping; now explicit sidebar/track focus |
| D. VIEW / Sel push | Unidentified | Requires ordered input evidence; no guessed binding |

Incoming right FX knobs share numbers with outgoing meters; direction is significant. Captured palette numbers do not establish RGB bit layout or named colors. Pad code 0 is the captured clear; 5 is only a candidate peak meter value inherited from the earlier channel-meter test, not a captured pad color.

Pinned native source confirms the controls used: `[EffectRack1_EffectUnitN]` mix/enabled/group_[ChannelN]_enable; slot groups `_Effect1..3` loaded/enabled/meta/next_effect. Unit wet/dry starts dry in the default engine, so use Shift+first FX knob. The mapping preserves existing routes and mix. FX bank routing uses the last observed deck on that side, initially 1/2; dedicated deck-select CC and FX assignment controls need further evidence.

`[Main],vu_meter_left/right` and `peak_indicator_left/right` are the actual stereo engine controls. The VU signal is already after software main gain/balance/talkover. The master handler never applies channel gain again. Hardware-only analog controls may not be reflected.

`[Library],focused_widget` identifies sidebar=2, tracks=3. `GoToItem` expands/enters a sidebar item but can load when called from tracks; the handler calls it only from sidebar. The existing exporter supports `BrowseTableModel`, so native code changes were unnecessary for filesystem rows. Both LCDs mirror the same bounded active HDMI browser page. Captured B0 16 00/01 remains an optional visibility experiment, not a verified three-view cycle.

## Hardware acceptance

1. Install v056 with existing options retained; verify MUSIC still appears and loads. Keep HDMI waveforms disabled.
2. On each side, press all three FX buttons, rotate the corresponding knobs, Shift+button to change effect, Shift+first knob to set wet/dry. Confirm audible effect and LED state. Repeat on layers 3/4 after touching a deck control. Check HDMI routing for intentionally retained extra routes.
3. Assign/clear cues, enter loop/roll modes, load/play a sampler, switch deck layers. Photograph the colors with their pad numbers. Confirm unloaded/unsupported pads clear and rolls release when switching modes.
4. With speakers quiet, run the optional seven-second lamp test. Observe both master strips and all four channel meters: zero should clear; record which step reaches red. Return vuTest to false. Then compare real left/right playback, pause and silence with F12 master meter values.
5. Try `browser-view-examples/right/BiteDJ_NV_browser_view.txt`: compare rows and selection with HDMI, browse MUSIC, enter folders and load on each deck. Note physical navigation button identity. Verify the view itself; the command interpretation remains provisional.
6. For D. VIEW, provide a fresh ordered left/right/layer input sequence and F12, plus labelled working-software capture/video for outgoing Performance1/Performance2/Library commands. No existing capture establishes this complete cycle.

No new physical hardware result is claimed. Software regression tests cover behavior and generated MIDI; they cannot establish firmware color meanings, physical LED labels or LCD display response. Artwork, cue/loop overlays, detailed LCD FX graphics, touch-EQ and Slicer remain unfinished.
