# Original Numark NV display transport — capture findings

This is an offline protocol checkpoint, not a working LCD driver. No capture
is replayed by the controls update, and it does not enable the Pi waveforms.

## Directly observed

| USB device | Function from descriptors | MIDI endpoints |
|---|---|---|
| `15e4:1005` | Main controller MIDI | OUT `01`, IN `82` |
| `15e4:1033` | Left display MIDI **and USB audio** | MIDI OUT `03`, IN `83`; separate isochronous audio endpoints |
| `15e4:2033` | Right display MIDI | OUT `03`, IN `83` |

Both display MIDI interfaces use USB class `01`, subclass `03`. Screen writes
travel as USB-MIDI SysEx on these dedicated devices. There is no need to
detach the USB audio driver to use a raw vendor/bulk transport: the left
device's audio/MIDI ownership must be preserved in any future implementation.

The observed message has this layout:

```text
F0 47 <screen> 33 05 <command> <outer_hi> <outer_lo>
<packed_hi> <packed_lo> <packed_data...> F7
```

`screen` is `10` for the left device and `20` for the right device.
Both lengths are 14-bit, most significant 7 bits first. `outer_length` equals
the packed-data length plus 2; total MIDI message length is `outer_length+9`.
Packed data is an LSB-first bitstream: eight original bytes are represented
by up to ten 7-bit MIDI-safe bytes. Unused final bits are zero. The included
`display_protocol.py` verifies lengths, padding and exact re-encoding.

All **4,328** observed display messages validate against that framing and
packing. Unpacking command `30` gives a 1,024-byte palette-like table;
command `22` includes UTF-16LE text after a leading selector byte. These are
strong checks on the packing interpretation, not proof of all field meanings.

| Command | Decoded payload size | Observation / provisional interpretation |
|---|---:|---|
| `01` | 249 | Track/text-like record; fixed strings are visible when nonempty |
| `04` | 19 | Numeric record; field units and roles still need isolated tests |
| `05` | 15 | Frequent deck/playhead-like update |
| `07` | 517 | Waveform/overview-like block; sample/palette structure unresolved |
| `09` | 2,170 | Frequent large waveform-like update; fields unresolved |
| `0A` | 97 | Longer text/metadata-like block |
| `21` | 131 | Browser/category-like text block; exact record fields unresolved |
| `22` | 129 | UTF-16LE label record, including a visible “Stems” label |
| `24` | 361 | Browser/list-like block, often empty |
| `30` | 1,024 | Palette-like table, 256 four-byte entries |
| `31` | 2,049 | Large data record; interpretation unresolved |

Command meanings in this table are **inferences**. Do not synthesize or send
these data records from the inferred descriptions. Numeric variants and
other command sizes are retained by the generic decoder.

## Remaining implementation

1. Label waveform/overview and playhead fields using a controlled recording:
   one known track, paused then playing, one zoom change at a time, and a
   simultaneous screen video or timestamped action list. Existing captures
   already establish the transport; they lack that semantic synchronization.
2. Access the app's analyzed waveform and metadata while Pi rendering remains
   disabled. The preserved app binary has no `getWaveform`, `getWaveformData`
   or `getTrackMetadata` method strings. That is static evidence, not a runtime
   API probe. A source change or a separate analysis bridge may be needed.
3. Bind independent scripts to the left/right LCD MIDI ports, use cached
   analysis, bound update frequency and avoid any driver detachment or device
   reset. Keep the working audio/controller MIDI mapping intact.
4. Verify a small known display update on real hardware before adding animated
   scrolling waveforms, then check the existing audio-underflow telemetry.

The supplied Mixxx URLs are references, not a source checkout matching the
current BiteDJ executable. Rebuilding an upstream/old mapping fork alone
would not establish preservation of the appliance's real-time changes.
