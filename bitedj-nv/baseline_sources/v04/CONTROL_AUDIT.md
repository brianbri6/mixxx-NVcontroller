# Original Numark NV controls audit — v0.4

The Pi4 4GB is the working baseline, with the Pi display waveforms switched
off by the user. This update preserves the saved settings. “Implemented”
describes code; it does not mean physical testing is complete.

| Area | Input/control status | Feedback status / next check |
|---|---|---|
| Platter rotation | **Decoder corrected** using both actual position bytes; 7,520 positions checked | Verify direction and measured ticks per full turn on both platters |
| Platter touch and Scratch | Touch note on/off supported; immediate stop on touch | Scratch-mode LED initialized and updated; test hold/release and CD mode |
| Pitch fader | Complete 14-bit pair applied once, exact zero center, soft takeover retained | White zero light candidate added at note `0x51`; verify on both sides and layers |
| Pitch pickup arrows | Soft takeover remains active | Not added; arrow behavior needs a focused pitch/Sync/layer capture |
| Channel VU | Read-only Mixxx `vu_meter` values | Candidate CCs `4B/4C/4A/4D` for decks 1/2/3/4; 20 Hz maximum, change-only, captured values 0..4. Verify strips and full scale |
| Play/Cue | Existing transport assignments retained | `play_indicator` and `cue_indicator` reflect software state, including blinking |
| Sync/Slip | Existing assignments retained | State LEDs retained |
| Headphone cue/PFL | Existing assignments retained | Feedback added on captured output notes `35/36/34/37`; test each channel |
| Channel volume, gain, EQ, filters and crossfader | Existing assignments retained | Test physical channel order and range; no new knob-touch functions |
| Browse/load | Existing assignments retained | LCD browser display unavailable |
| Hotcue/loop/roll/sampler mode | Existing functions retained | Active mode-button feedback added; pad RGB feedback remains incomplete |
| Deck layers 1/3 and 2/4 | Deck-specific MIDI channels retained | All four platter byte pairs mapped; verify physical switching under touch |
| Advanced FX and routing buttons | Incomplete/unimplemented | Next input/output mapping pass, after platter and meters |
| Touch EQ/FX/filter modes | Unimplemented | Require isolated touch/button captures |
| Slicer and its alternate page | Unimplemented | Selecting the existing Slicer binding disables pad actions |
| Beatkeeper, fader start, crossfader assign/curve | Incomplete/unimplemented | Must not label nearby CC `48/49` as master meters without isolating their purpose |
| NV LCD waveforms/track metadata | Separate display devices and packet framing decoded | **No live driver installed**; waveform fields and app bridge remain |

The supplied output capture directly proves messages exist at these addresses.
It does not directly label the physical LEDs. Pitch-zero and VU semantic
assignments remain explicitly provisional until the hardware checklist passes.

The source mapping still does not offer full original-NV parity. A focused
test of one control/channel at a time makes the next change attributable.
