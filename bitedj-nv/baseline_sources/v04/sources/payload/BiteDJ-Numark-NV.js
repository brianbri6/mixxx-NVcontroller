/* SPDX-License-Identifier: GPL-2.0-only
 * Original Numark NV controls test v0.4 for BiteDJ / Mixxx 2.5.
 * MIDI addresses: Hidetsugu Takahashi's Numark-NV preset, revision
 * 6e999daaf62322e351169b364f071dfb1df4e4c1, and NumarkNVVDJ.pcapng.
 * This script replaces the older preset's broken/undefined handlers.
 * Platter counter verified against both user-supplied platter captures.
 * NV LCDs, touch-EQ, advanced FX pages and Slicer are not implemented.
 */
'use strict';
var BiteDJNV = {};
BiteDJNV.jogSensitivity = 0.25;
// Preserve the previous nominal resolution until a measured full turn is available.
BiteDJNV.scratchTicksPerRevolution = 5600;
BiteDJNV.pitchCenterDeadband = 16; // 14-bit ADC counts, around 8192.
// Only the observed 0..4 meter values are used in this first hardware test.
BiteDJNV.vuMaximum = 4;
BiteDJNV.vuAddresses = [0x4b, 0x4c, 0x4a, 0x4d]; // Decks 1,2,3,4; 3-1-2-4 mixer layout.
BiteDJNV.jogCounters = [];
BiteDJNV.touchStats = [];
BiteDJNV.ledValues = {};
BiteDJNV.meterTimer = 0;
BiteDJNV.shift = [false, false, false, false];
BiteDJNV.vinyl = [true, true, true, true];
BiteDJNV.mode = ['cue', 'cue', 'cue', 'cue'];
BiteDJNV.bytes = {};
BiteDJNV.holds = {};
BiteDJNV.connections = [];
BiteDJNV.loops = [0.125, 0.25, 0.5, 1, 2, 4, 8, 16];
BiteDJNV.ranges = [0.08, 0.16, 0.50];
BiteDJNV.cc = {
    "7": [
        "[Master]",
        "crossfader"
    ],
    "8": [
        "[Channel1]",
        "volume"
    ],
    "9": [
        "[EqualizerRack1_[Channel1]_Effect1]",
        "parameter1"
    ],
    "10": [
        "[EqualizerRack1_[Channel1]_Effect1]",
        "parameter2"
    ],
    "11": [
        "[EqualizerRack1_[Channel1]_Effect1]",
        "parameter3"
    ],
    "12": [
        "[Channel1]",
        "pregain"
    ],
    "13": [
        "[Channel2]",
        "volume"
    ],
    "14": [
        "[EqualizerRack1_[Channel2]_Effect1]",
        "parameter1"
    ],
    "15": [
        "[EqualizerRack1_[Channel2]_Effect1]",
        "parameter2"
    ],
    "16": [
        "[EqualizerRack1_[Channel2]_Effect1]",
        "parameter3"
    ],
    "17": [
        "[Channel2]",
        "pregain"
    ],
    "18": [
        "[Master]",
        "headMix"
    ],
    "19": [
        "[Channel3]",
        "volume"
    ],
    "20": [
        "[EqualizerRack1_[Channel3]_Effect1]",
        "parameter1"
    ],
    "21": [
        "[EqualizerRack1_[Channel3]_Effect1]",
        "parameter2"
    ],
    "22": [
        "[EqualizerRack1_[Channel3]_Effect1]",
        "parameter3"
    ],
    "23": [
        "[Channel3]",
        "pregain"
    ],
    "24": [
        "[Channel4]",
        "volume"
    ],
    "25": [
        "[EqualizerRack1_[Channel4]_Effect1]",
        "parameter1"
    ],
    "26": [
        "[EqualizerRack1_[Channel4]_Effect1]",
        "parameter2"
    ],
    "27": [
        "[EqualizerRack1_[Channel4]_Effect1]",
        "parameter3"
    ],
    "28": [
        "[Channel4]",
        "pregain"
    ],
    "68": [
        "[Master]",
        "headGain"
    ],
    "90": [
        "[QuickEffectRack1_[Channel3]]",
        "super1"
    ],
    "91": [
        "[QuickEffectRack1_[Channel1]]",
        "super1"
    ],
    "92": [
        "[QuickEffectRack1_[Channel2]]",
        "super1"
    ],
    "93": [
        "[QuickEffectRack1_[Channel4]]",
        "super1"
    ]
};
BiteDJNV.deck = function(group) {
    var m = /^\[Channel([1-4])\]$/.exec(group);
    return m ? Number(m[1]) : 0;
};
BiteDJNV.pressed = function(value, status) { return (status & 0xf0) !== 0x80 && value > 0; };
BiteDJNV.pulse = function(group, key) { engine.setValue(group, key, 1); engine.setValue(group, key, 0); };
BiteDJNV.toggle = function(group, key) { engine.setValue(group, key, engine.getValue(group, key) ? 0 : 1); };
BiteDJNV.hold = function(id, group, key, down) {
    var previous = BiteDJNV.holds[id];
    if (!down) {
        if (previous) { engine.setValue(previous[0], previous[1], 0); delete BiteDJNV.holds[id]; }
    } else if (!previous) {
        BiteDJNV.holds[id] = [group, key];
        engine.setValue(group, key, 1);
    }
};
BiteDJNV.relative = function(value) {
    // Browse remains a relative encoder. The platter uses jogCounters instead.
    return value < 64 ? value : (value === 64 ? 0 : value - 128);
};
BiteDJNV.highres = function(id, value, lsb) {
    var b = BiteDJNV.bytes[id] || { msb: 64, lsb: 0 };
    b[lsb ? 'lsb' : 'msb'] = value;
    BiteDJNV.bytes[id] = b;
    return (128 * b.msb + b.lsb) / 16383;
};
BiteDJNV.mixer = function(channel, control, value, status, group) {
    var low = control >= 0x27 && control <= 0x3c;
    var cc = low ? control - 0x20 : control;
    var target = BiteDJNV.cc[cc];
    if (!target) { return; }
    var p = cc >= 0x07 && cc <= 0x1c ? BiteDJNV.highres('m' + cc, value, low) : value / 127;
    engine.setParameter(target[0], target[1], p);
};
BiteDJNV.pitch = function(channel, control, value, status, group) {
    var d = BiteDJNV.deck(group);
    if (!d) { return; }
    var b = BiteDJNV.bytes['p' + d] || { msb: null };
    BiteDJNV.bytes['p' + d] = b;
    if (control === 0x01) { b.msb = value; return; }
    if (control !== 0x21 || b.msb === null) { return; }
    var raw = b.msb * 128 + value;
    b.msb = null;
    // Exact 0% at the hardware center, with a small ADC deadband.
    var parameter = Math.abs(raw - 8192) <= BiteDJNV.pitchCenterDeadband ? 0.5 :
        (raw < 8192 ? raw / 16384 : 0.5 + (raw - 8192) / 16382);
    engine.setParameter(group, 'rate', parameter);
};
BiteDJNV.jog = function(channel, control, value, status, group) {
    var d = BiteDJNV.deck(group);
    if (!d) { return; }
    var state = BiteDJNV.jogCounters[d - 1] || { low: null, previous: null };
    BiteDJNV.jogCounters[d - 1] = state;
    // The NV sends LOW byte on CC 0x00, then HIGH byte on CC 0x20.
    // These are an absolute wrapping 14-bit counter, not relative MIDI ticks.
    if (control === 0x00) { state.low = value; return; }
    if (control !== 0x20 || state.low === null) { return; }
    var position = value * 128 + state.low;
    state.low = null;
    var previous = state.previous;
    state.previous = position;
    if (previous === null) { return; } // Acquire a baseline without moving the deck.
    var delta = position - previous;
    if (delta > 8191) { delta -= 16384; }
    else if (delta < -8192) { delta += 16384; }
    if (!delta) { return; }
    var stats = BiteDJNV.touchStats[d - 1];
    if (stats) {
        stats.ticks += delta; stats.travel += Math.abs(delta); stats.samples++;
        stats.largest = Math.max(stats.largest, Math.abs(delta));
    }
    if (engine.isScratching(d)) { engine.scratchTick(d, delta); }
    else { engine.setValue(group, 'jog', delta * BiteDJNV.jogSensitivity); }
};
BiteDJNV.touch = function(channel, control, value, status, group) {
    var d = BiteDJNV.deck(group);
    if (!d) { return; }
    if (BiteDJNV.pressed(value, status) && BiteDJNV.vinyl[d - 1]) {
        if (BiteDJNV.touchStats[d - 1]) { return; }
        BiteDJNV.jogCounters[d - 1] = { low: null, previous: null };
        BiteDJNV.touchStats[d - 1] = { ticks: 0, travel: 0, samples: 0, largest: 0 };
        engine.scratchEnable(d, BiteDJNV.scratchTicksPerRevolution,
            33 + 1 / 3, 1 / 8, 1 / 256, false);
    } else {
        engine.scratchDisable(d, true);
        var stats = BiteDJNV.touchStats[d - 1];
        if (stats) {
            console.info('BiteDJNV touch-release deck=' + d + ' signed_ticks=' + stats.ticks +
                ' travel_ticks=' + stats.travel + ' samples=' + stats.samples + ' largest=' + stats.largest);
        }
        BiteDJNV.touchStats[d - 1] = null;
    }
};
BiteDJNV.button = function(channel, control, value, status, group) {
    var d = BiteDJNV.deck(group), down = BiteDJNV.pressed(value, status);
    if (!d) { return; }
    var i = d - 1, shift = BiteDJNV.shift[i];
    if (control === 0x0d) { BiteDJNV.shift[i] = down; return; }
    if (control === 0x20) {
        if (!down) { BiteDJNV.hold('cue' + d, group, 'cue_default', false); return; }
        if (shift) { if (down) { BiteDJNV.pulse(group, 'start'); } }
        else { BiteDJNV.hold('cue' + d, group, 'cue_default', true); }
        return;
    }
    if (control === 0x0b) {
        if (!down) { BiteDJNV.hold('reverse' + d, group, 'reverseroll', false); return; }
        if (shift) { if (down) { BiteDJNV.toggle(group, 'reverse'); } }
        else { BiteDJNV.hold('reverse' + d, group, 'reverseroll', true); }
        return;
    }
    if (control === 0x10 || control === 0x11) {
        engine.setValue(group, control === 0x10 ? 'rate_temp_down' : 'rate_temp_up', down ? 1 : 0);
        return;
    }
    if (!down) { return; }
    switch (control) {
    case 0x21: BiteDJNV.toggle(group, 'play'); break;
    case 0x1f: BiteDJNV.toggle(group, 'sync_enabled'); break;
    case 0x05: BiteDJNV.pulse(group, 'LoadSelectedTrack'); break;
    case 0x0a: BiteDJNV.toggle(group, 'slip_enabled'); break;
    case 0x0e: BiteDJNV.pulse(group, 'loop_halve'); break;
    case 0x0f: BiteDJNV.pulse(group, 'loop_double'); break;
    case 0x02: BiteDJNV.pulse(group, 'bpm_tap'); break;
    case 0x0c:
        BiteDJNV.vinyl[i] = !BiteDJNV.vinyl[i];
        if (!BiteDJNV.vinyl[i]) { engine.scratchDisable(d, true); BiteDJNV.touchStats[i] = null; }
        BiteDJNV.sendLED(0x90 + d, 0x0c, BiteDJNV.vinyl[i] ? 127 : 0);
        break;
    case 0x01:
        if (shift) { BiteDJNV.toggle(group, 'keylock'); }
        else {
            var current = engine.getValue(group, 'rateRange'), next = 0;
            for (var r = 0; r < BiteDJNV.ranges.length; r++) {
                if (Math.abs(current - BiteDJNV.ranges[r]) < 0.001) { next = (r + 1) % BiteDJNV.ranges.length; }
            }
            engine.setValue(group, 'rateRange', BiteDJNV.ranges[next]);
        }
        break;
    }
};
BiteDJNV.padMode = function(channel, control, value, status, group) {
    var d = BiteDJNV.deck(group);
    if (!d || !BiteDJNV.pressed(value, status)) { return; }
    var modes = { 26: 'cue', 28: 'loop', 27: 'roll', 29: 'sampler', 30: 'disabled' };
    if (modes[control]) { BiteDJNV.mode[d - 1] = modes[control]; BiteDJNV.padModeLEDs(d); }
};
BiteDJNV.pad = function(channel, control, value, status, group) {
    var d = BiteDJNV.deck(group), n = control - 0x47, down = BiteDJNV.pressed(value, status);
    if (!d || n < 0 || n > 7) { return; }
    var id = 'pad' + d + ':' + n;
    if (!down) { BiteDJNV.hold(id, group, '', false); return; }
    var mode = BiteDJNV.mode[d - 1];
    if (mode === 'cue') {
        var key = 'hotcue_' + (n + 1) + (BiteDJNV.shift[d - 1] ? '_clear' : '_activate');
        BiteDJNV.hold(id, group, key, true);
    } else if (mode === 'loop') {
        if (down) { BiteDJNV.pulse(group, 'beatloop_' + BiteDJNV.loops[n] + '_toggle'); }
    } else if (mode === 'roll') {
        BiteDJNV.hold(id, group, 'beatlooproll_' + BiteDJNV.loops[n] + '_activate', true);
    } else if (mode === 'sampler' && down) {
        BiteDJNV.pulse('[Sampler' + (n + 1) + ']', BiteDJNV.shift[d - 1] ? 'stop' : 'cue_gotoandplay');
    }
};
BiteDJNV.browse = function(channel, control, value) {
    var delta = BiteDJNV.relative(value);
    if (delta) { engine.setValue('[Library]', 'MoveVertical', delta); }
};
BiteDJNV.sidebar = function(channel, control, value, status) {
    if (BiteDJNV.pressed(value, status)) { BiteDJNV.pulse('[Playlist]', 'ToggleSelectedSidebarItem'); }
};
BiteDJNV.pfl = function(channel, control, value, status, group) {
    if (BiteDJNV.pressed(value, status)) { BiteDJNV.toggle(group, 'pfl'); }
};
BiteDJNV.sendLED = function(status, control, value) {
    var id = status + ':' + control;
    if (BiteDJNV.ledValues[id] !== value) {
        midi.sendShortMsg(status, control, value);
        BiteDJNV.ledValues[id] = value;
    }
};
BiteDJNV.padModeLEDs = function(deck) {
    var notes = { cue: 0x1a, roll: 0x1b, loop: 0x1c, sampler: 0x1d };
    Object.keys(notes).forEach(function(mode) {
        BiteDJNV.sendLED(0x90 + deck, notes[mode], BiteDJNV.mode[deck - 1] === mode ? 127 : 0);
    });
    BiteDJNV.sendLED(0x90 + deck, 0x1e, 0); // Slicer remains unavailable.
};
BiteDJNV.updateMeters = function() {
    for (var deck = 1; deck <= 4; deck++) {
        var value = engine.getValue('[Channel' + deck + ']', 'vu_meter');
        var level = isFinite(value) && value > 0 ? Math.ceil(Math.min(value, 1) * BiteDJNV.vuMaximum) : 0;
        BiteDJNV.sendLED(0xb0, BiteDJNV.vuAddresses[deck - 1], level);
    }
};
BiteDJNV.init = function() {
    console.info('BiteDJNV controls v0.4: 14-bit absolute platter decoder; LED test feedback');
    if (BiteDJNV.meterTimer) { engine.stopTimer(BiteDJNV.meterTimer); }
    BiteDJNV.connections.forEach(function(c) { c.disconnect(); });
    BiteDJNV.bytes = {};
    BiteDJNV.holds = {};
    BiteDJNV.connections = [];
    BiteDJNV.jogCounters = [];
    BiteDJNV.touchStats = [];
    BiteDJNV.ledValues = {};
    for (var d = 1; d <= 4; d++) {
        BiteDJNV.shift[d - 1] = false;
        BiteDJNV.mode[d - 1] = 'cue';
        BiteDJNV.vinyl[d - 1] = true;
        engine.softTakeover('[Channel' + d + ']', 'rate', true);
        BiteDJNV.sendLED(0x90 + d, 0x0c, 127);
        BiteDJNV.padModeLEDs(d);
        (function(deck) {
            var keys = { play_indicator: 0x21, cue_indicator: 0x20, sync_enabled: 0x1f, slip_enabled: 0x0a };
            Object.keys(keys).forEach(function(key) {
                var c = engine.makeConnection('[Channel' + deck + ']', key, function(value) {
                    BiteDJNV.sendLED(0x90 + deck, keys[key], value ? 127 : 0);
                });
                BiteDJNV.connections.push(c);
                c.trigger();
            });
            var center = engine.makeConnection('[Channel' + deck + ']', 'rate', function(value) {
                BiteDJNV.sendLED(0x90 + deck, 0x51, Math.abs(value) < 0.000001 ? 127 : 0);
            });
            BiteDJNV.connections.push(center); center.trigger();
            var cueNotes = [0x35, 0x36, 0x34, 0x37];
            var pfl = engine.makeConnection('[Channel' + deck + ']', 'pfl', function(value) {
                BiteDJNV.sendLED(0x90, cueNotes[deck - 1], value ? 127 : 0);
            });
            BiteDJNV.connections.push(pfl); pfl.trigger();
        })(d);
    }
    BiteDJNV.updateMeters();
    BiteDJNV.meterTimer = engine.beginTimer(50, BiteDJNV.updateMeters);
    // Current-position request used by the original NV community mapping.
    var request = [0xf0, 0x00, 0x20, 0x7f, 0x03, 0x01, 0xf7];
    midi.sendSysexMsg(request, request.length);
};
BiteDJNV.shutdown = function() {
    if (BiteDJNV.meterTimer) { engine.stopTimer(BiteDJNV.meterTimer); BiteDJNV.meterTimer = 0; }
    Object.keys(BiteDJNV.holds).forEach(function(id) {
        BiteDJNV.hold(id, '', '', false);
    });
    BiteDJNV.connections.forEach(function(c) { c.disconnect(); });
    BiteDJNV.connections = [];
    for (var d = 1; d <= 4; d++) { engine.scratchDisable(d); }
    Object.keys(BiteDJNV.ledValues).forEach(function(id) {
        var address = id.split(':'); midi.sendShortMsg(Number(address[0]), Number(address[1]), 0);
    });
    BiteDJNV.jogCounters = []; BiteDJNV.touchStats = []; BiteDJNV.ledValues = {};
};
