BiteDJ Pi4 / original Numark NV Controls Test v0.4
================================================

This is a CONTROLS UPDATE for the working Pi4 v0.3 SD card, not a flashable
image. It installs a corrected platter decoder and experimental LED feedback.
Your audio routing/buffer, 720p configuration and saved waveform-off setting
are preserved. The NV LCDs do not gain live waveforms in this update.

INSTALL ON YOUR EXISTING CARD
-----------------------------
1. Shut down the Pi normally and remove power. Put its SD card in your computer.
2. Extract this ZIP. Open the card's BOOT/SHARKBOOT partition: the one containing
   config.txt, cmdline.txt and initramfs.img. Keep at least 20 MB free there.
3. Copy the current initramfs.img to your computer as a backup. Then copy
   install/initramfs.img from this ZIP to that BOOT partition, replacing the
   existing file. Do not copy the entire ZIP, flash it in Imager, or replace
   config.txt/cmdline.txt. No Python installation on your computer is needed.
4. Eject the card, put it back in the Pi4 and boot with the NV connected.
   The update backs up the two original mapping files before changing them.
   It accepts only the exact Pi4 v0.3 mappings; a custom mapping is preserved.
5. The existing enabled preset uses the same filename, so it should load the
   update. Its displayed name becomes 'Numark NV (BiteDJ Pi4 Controls Test v0.4)'.
   If necessary select it in Devices and Apply, as on the previous image.

BOOT/BiteDJ_NV_v04_update.txt records INSTALLED, ROLLED BACK, or NOT INSTALLED.
Read it on your computer after a normal shutdown if the update does not appear.
The kernel, Mixxx executable, graphics/CPU tuning and diagnostics are retained.
This modifies the controller mapping only. It does not update NV firmware.

WHAT WAS WRONG WITH THE PLATTER
-------------------------------
The two captures contain 7,520 complete platter positions. The NV sends a
14-bit ABSOLUTE counter: CC 0x00 is the low byte, followed by CC 0x20 as the
high byte. The old mapping treated CC 0x00 as relative two's-complement
movement and ignored CC 0x20. Thus the same gradual physical movement could
produce oversized ticks, wrong signs and discontinuities at byte boundaries.

The new mapping joins each pair once, subtracts the previous position and
handles the 16,383 -> 0 and 0 -> 16,383 wraps. The first complete position
establishes a baseline without moving the track. Touch stops playback
immediately in vinyl mode; release resumes with the normal scratch ramp.
All observed position sequences pass regression checks on all four bindings.
Clockwise/anticlockwise feel and movement distance still need a physical test.

FOCUSED TEST: DO THESE IN ORDER
-------------------------------
1. Platter: load one track and enable Scratch/Vinyl. While paused, touch the
   top and slowly move clockwise, then anticlockwise. The playhead should
   follow each direction smoothly without jumping. Repeat while playing:
   touch should hold/scratch, release should resume. Turn only the outside
   rim without touching the top to check pitch bend. Repeat on the right deck.
2. Scratch distance: mark a reference point on the platter. With its top held,
   rotate it exactly ONE full clockwise turn, then release. Do the same on
   the other deck. Note whether the movement is too small/large or reversed.
   A touch-release log records the signed tick total for calibration. The
   nominal 5,600 ticks/revolution is retained from v0.3; the supplied captures
   do not identify a measured full turn, so that scale is not yet verified.
3. Pitch: move the pitch away from zero and back to its center. Check that the
   displayed software pitch reaches exactly 0% and the white light responds.
   Both pitch bytes are joined before applying a value. A small 16-count ADC
   deadband keeps the center exactly zero. Soft takeover remains enabled, so
   catch the software pitch first when changing deck layers or using Sync.
4. VU meters: play ONLY deck 1, then 2, then 3, then 4, one at a time. Check
   whether the meter for that channel moves and which strip actually lights.
   Normal NV mixer order is 3-1-2-4. This first test uses only captured levels
   0..4 and a provisional strip assignment. Full scale, remaining segments
   and clip indication still need calibration; this is not a calibrated meter.
5. Feedback: check Play/Cue, Sync, Slip, headphone cue, Scratch and pad-mode
   buttons. Slicer remains unavailable and has no active mode light.

If platter distance/direction or an LED/strip is wrong, pause playback and
press F12 to export the existing diagnostic ZIP to BOOT. Send that ZIP with
the deck number, physical action, and the meter/light that responded.
The one-turn touch totals are in its app log. F9 can start a fresh OS timeline;
it does not clear all prior app logs, so describe the order of your turns.

ROLL BACK WITHOUT REFLASHING
----------------------------
Shut down, open BOOT on your computer and copy the empty file
rollback/BiteDJ_NV_v04_rollback into BOOT. Reboot with the v0.4 initramfs still
in place. It restores the backed-up v0.3 mapping and writes ROLLED BACK into
BiteDJ_NV_v04_update.txt. After that shutdown, restore your saved original
initramfs.img if desired. Keep the rollback marker while the v0.4 initramfs
remains installed; removing the marker allows the update to apply again.
Restoring the old initramfs alone after installation does not undo the mapping.

LED EVIDENCE / LIMITS
---------------------
The captures show the output addresses, not a video of which LEDs change.
Pitch-zero note 0x51 is inferred from the state transitions and existing NV
control layout. The active channel-1 VU candidate is CC 0x4B; the other channel
assignments are inferred from adjacent cleared addresses and mixer order.
These are hardware test candidates, not a claim that every light is verified.
Only short MIDI LED messages are added; meter updates run at most 20 times per
second and unchanged levels are not resent. No captured display data is replayed.

LCD WAVEFORMS: PROGRESS, NOT INSTALLED
------------------------------------
The captures identify two separate display MIDI ports (15e4:1033 / 15e4:2033).
The left-display USB device also contains the audio interface, so its audio
driver must stay attached. The LCD packets are framed SysEx, with packed
7-bit payloads. The included offline decoder validates all 4,328 display
messages from the three captures. Palette/text records decode consistently.
The larger waveform-like command blocks still need field identification and
a bridge from the app's waveform analysis to those display ports. The running
binary exposes no getWaveform/getWaveformData/getTrackMetadata method names.
These facts do not establish a functioning waveform driver. Turning off
waveforms on the Pi does not route them to the NV screens automatically.
See CONTROL_AUDIT.md and DISPLAY_PROTOCOL.md for the remaining work.

VALIDATION / SOURCE
-------------------
8 JavaScript regression/feedback tests, 5 installer/rollback/recovery tests,
307 unique XML input bindings and the existing diagnostic forwarding checks
pass. The initramfs round trip preserves 990 original members, modifies only
the boot init hook and adds the fixed installer. The tests use simulations and
real capture bytes; this update has not been run on a physical Pi/NV here.

Sources include the mapping, installer, builder, fixtures and offline decoders.
The two input captures and music are not bundled. Source mappings are GPL-2.0;
new packaging/decoder/test tools are MIT, with licenses included. Original
image/application licensing remains as in the Pi4 v0.3 package.

Hardware references:
https://www.numark.com/images/product_downloads/NV-UserGuide-v1.2.pdf
https://virtualdj.com/manuals/hardware/numark/nv/layout/decks.html
https://virtualdj.com/manuals/hardware/numark/nv/layout/mixer.html
Mixxx API reference:
https://github.com/mixxxdj/mixxx/wiki/Midi-Scripting
https://manual.mixxx.org/2.5/en/chapters/appendix/mixxx_controls
