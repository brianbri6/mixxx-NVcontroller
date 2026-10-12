# SPDX-License-Identifier: MIT
"""Offline interpretation of observed LCD fields. No MIDI output functions.

Offsets apply AFTER the NV seven-bit bitstream has been unpacked. Uncertain
bytes retain neutral names rather than being assigned a guessed function.
"""
import struct

LENGTHS = {1: 249, 2: 65, 3: 9, 4: 19, 5: 15, 6: 7, 7: 517, 8: 7,
           9: 2170, 10: 97, 16: 10, 32: 10, 33: 131, 34: 129,
           35: 10, 36: 361, 48: 1024, 49: 2049}


def text(raw, wide=False):
    if wide:
        return raw.decode('utf-16-le').split('\0', 1)[0]
    return raw.split(b'\0', 1)[0].decode('ascii')


def decode_fields(command, raw):
    if command not in LENGTHS or len(raw) != LENGTHS[command]:
        raise ValueError('Unobserved command/length')
    if command == 1:
        return {'selector': raw[0], 'title': text(raw[1:97], True),
                'artist': text(raw[97:193], True), 'original_bpm': text(raw[193:199]),
                'key': text(raw[199:241], True), 'color_or_style_hex': raw[241:245].hex(),
                'duration_ms': struct.unpack_from('<I', raw, 245)[0]}
    if command == 2:
        return {'selector': raw[0], 'opaque_64_bytes_hex': raw[1:].hex(),
                'all_zero_after_selector': not any(raw[1:])}
    if command == 3:
        return {'selector': raw[0], 'candidate_cue_palette_indices': list(raw[1:])}
    if command == 4:
        return {'selector': raw[0], 'bpm': text(raw[1:8]),
                'pitch_percent': text(raw[8:15]), 'range_percent': text(raw[15:19])}
    if command == 5:
        values = struct.unpack('<BIiHi', raw)
        return dict(zip(('selector', 'clock_ms', 'position_ms', 'angle_1024', 'speed_milli'), values))
    if command in (6, 8):
        return {'first_byte': raw[0], 'three_uint16_le': list(struct.unpack('<HHH', raw[1:]))}
    if command == 7:
        selector, chunk, size = struct.unpack('<BHH', raw[:5])
        if not 1 <= chunk <= 8 or size not in (256, 512):
            raise ValueError('Unexpected overview chunk')
        return {'selector': selector, 'chunk': chunk, 'valid_bytes': size,
                'nonzero_pixels': sum(bool(v) for v in raw[5:5+size])}
    if command == 9:
        selector, flag, timestamp, unit, size = struct.unpack('<BBIHH', raw[:10])
        if (flag, unit, size) != (1, 1, 2160):
            raise ValueError('Unexpected detail header')
        return {'selector': selector, 'fixed_byte': flag, 'timestamp_ms': timestamp,
                'fixed_uint16': unit, 'bitmap_bytes': size,
                'nonzero_pixels': sum(bool(v) for v in raw[10:])}
    if command == 10:
        return {'bank_observed_0_left_1_right': raw[0],
                'labels': [text(raw[i:i+32]) for i in (1, 33, 65)]}
    if command == 16:
        return {'selector': raw[0], 'mode_or_flag': raw[1],
                'candidate_loop_start_end_i32': list(struct.unpack('<ii', raw[2:]))}
    if command in (32, 35):
        return {'candidate_selected_visible_row': raw[0],
                'opaque_tail_hex': raw[1:].hex(),
                'candidate_u16_u32_u32_layout': list(struct.unpack('<HII', raw))}
    if command == 33:
        return {'visible_row': raw[0], 'unknown_type_or_flags': raw[1],
                'unknown_depth_or_flags': raw[2], 'folder_name': text(raw[3:], True)}
    if command == 34:
        return {'unknown_type_or_flags': raw[0], 'header_text': text(raw[1:], True)}
    if command == 36:
        return {'visible_row': raw[0], 'title': text(raw[1:257], True),
                'artist': text(raw[257:353], True), 'bpm_text': text(raw[353:357]),
                'unknown_style_hex': raw[357:].hex()}
    if command == 48:
        return {'entries': 256, 'bytes_per_entry': 4, 'layout': 'BGRA'}
    if command == 49:
        return {'selector': raw[0], 'nonzero_pairs': [
            {'slot': (i-1)//8, 'uint32_unknown_units': struct.unpack_from('<I', raw, i)[0],
             'float32_bpm_candidate': struct.unpack_from('<f', raw, i+4)[0]}
            for i in range(1, len(raw), 8) if any(raw[i:i+8])]}
    raise AssertionError('Missing decoder')


def encode_text_fields(command, fields):
    """Round-trip the newly identified text records OFFLINE; no transport.

The region widths fit every supplied example. Unknown type/style bytes are
required explicitly. This is not a claim of tested firmware string limits.
"""
    def region(value, size, wide=False):
        raw = value.encode('utf-16-le' if wide else 'ascii')
        if len(raw) > size - (2 if wide else 1) or '\0' in value:
            raise ValueError('Text does not fit observed region')
        return raw.ljust(size, b'\0')
    if command == 10:
        if len(fields['labels']) != 3:
            raise ValueError('Expected three effect labels')
        return bytes([fields['bank_observed_0_left_1_right']]) + b''.join(
            region(label, 32) for label in fields['labels'])
    if command == 33:
        return bytes([fields['visible_row'], fields['unknown_type_or_flags'],
                      fields['unknown_depth_or_flags']]) + region(fields['folder_name'], 128, True)
    if command == 34:
        return bytes([fields['unknown_type_or_flags']]) + region(fields['header_text'], 128, True)
    if command == 36:
        style = bytes.fromhex(fields['unknown_style_hex'])
        if len(style) != 4:
            raise ValueError('Expected four opaque style bytes')
        return (bytes([fields['visible_row']]) + region(fields['title'], 256, True) +
                region(fields['artist'], 96, True) + region(fields['bpm_text'], 4) + style)
    raise ValueError('Not a newly identified text command')
