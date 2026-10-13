/* SPDX-License-Identifier: GPL-2.0-only
 * Original Numark NV controls test v0.5.7 for BiteDJ / Mixxx 2.5.
 * MIDI addresses: Hidetsugu Takahashi's Numark-NV preset, revision
 * 6e999daaf62322e351169b364f071dfb1df4e4c1, and NumarkNVVDJ.pcapng.
 * This script replaces the older preset's broken/undefined handlers.
 * Platter counter verified against both user-supplied platter captures.
 * NV LCDs are handled by the separate native exporter/display service.
 * Three-slot FX banks, captured-palette pads and stereo master meters.
 * Touch-EQ, single-FX parameter pages and Slicer are not implemented.
 */
'use strict';
var BiteDJNV = {};
BiteDJNV.jogSensitivity = 0.25;
BiteDJNV.scratchSensitivity = 2.0;
// Preserve the previous nominal resolution until a measured full turn is available.
BiteDJNV.scratchTicksPerRevolution = 5600;
BiteDJNV.pitchCenterDeadband = 16; // 14-bit ADC counts, around 8192.
// 0..4 were captured; 5 is the candidate fifth/red segment, pending hardware test.
BiteDJNV.vuMaximum = 4;
BiteDJNV.vuPeakLevel = 5;
BiteDJNV.vuSilenceThreshold = 0.01;
BiteDJNV.vuFollowFader = true;
BiteDJNV.vuTest = false;
BiteDJNV.meterTicks = 0;
BiteDJNV.meterMotion = [];
BiteDJNV.inputDiagnostics = {};
BiteDJNV.inputDiagnosticCount = 0;
BiteDJNV.meterTestTicks = 0;
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
BiteDJNV.activeDeck = [0, 0]; // Left: 1/3, right: 2/4.
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
// Original-NV bank addresses are pinned in reference/nv; colors/meters in
// docs/control-feedback-evidence.json. Palette codes are not RGB triplets.
BiteDJNV.padPalette = [0, 3, 6, 12, 21, 48, 52];
BiteDJNV.padDefaults = [12, 52, 48, 21, 6, 3, 52, 21];
BiteDJNV.padColors = BiteDJNV.padDefaults.slice();
BiteDJNV.fxPressed = {};
BiteDJNV.sideDeck = function(side) { return BiteDJNV.activeDeck[side] || side + 1; };
BiteDJNV.fxAddress = function(control, knob) {
    var banks = knob ? [[4, 5, 6], [0x49, 0x4a, 0x4b]] : [[0x0f, 0x10, 0x11], [0x13, 0x14, 0x15]];
    for (var side = 0; side < 2; side++) {
        var slot = banks[side].indexOf(control);
        if (slot >= 0) { return {side: side, slot: slot + 1, unit: '[EffectRack1_EffectUnit' + (side + 1) + ']'}; }
    }
    return null;
};
BiteDJNV.fxButton = function(channel, control, value, status) {
    var target = BiteDJNV.fxAddress(control, false);
    if (!target || (status & 0x0f) !== 0) { return; }
    var down = BiteDJNV.pressed(value, status);
    if (!down) { delete BiteDJNV.fxPressed[control]; return; }
    if (BiteDJNV.fxPressed[control]) { return; }
    BiteDJNV.fxPressed[control] = true;
    var deck = BiteDJNV.sideDeck(target.side);
    var group = target.unit.slice(0, -1) + '_Effect' + target.slot + ']';
    if (BiteDJNV.shift[deck - 1]) {
        BiteDJNV.pulse(group, 'next_effect');
    } else {
        // Empty slots receive the next available effect only after a user press.
        var enable = !engine.getValue(group, 'loaded') || !engine.getValue(group, 'enabled');
        if (!engine.getValue(group, 'loaded')) { BiteDJNV.pulse(group, 'next_effect'); }
        engine.setValue(group, 'enabled', enable ? 1 : 0);
        if (enable) {
            engine.setValue(target.unit, 'enabled', 1);
            engine.setValue(target.unit, 'group_[Channel' + deck + ']_enable', 1);
        }
        // Preserve wet/dry and existing routes; Shift + first knob sets wet/dry.
    }
    console.info('BiteDJNV FX unit=' + (target.side + 1) + ' slot=' + target.slot +
        ' deck=' + deck + ' enabled=' + engine.getValue(group, 'enabled') +
        ' mix=' + engine.getValue(target.unit, 'mix'));
    BiteDJNV.updateFxLEDs();
};
BiteDJNV.fxKnob = function(channel, control, value, status) {
    var target = BiteDJNV.fxAddress(control, true);
    if (!target || status !== 0xb0 || value < 0 || value > 127) { return; }
    var deck = BiteDJNV.sideDeck(target.side);
    if (BiteDJNV.shift[deck - 1]) {
        if (target.slot === 1) { engine.setParameter(target.unit, 'mix', value / 127); }
    } else {
        engine.setParameter(target.unit.slice(0, -1) + '_Effect' + target.slot + ']', 'meta', value / 127);
    }
};
BiteDJNV.updateFxLEDs = function() {
    [[0x0f, 0x10, 0x11], [0x13, 0x14, 0x15]].forEach(function(notes, side) {
        var unit = '[EffectRack1_EffectUnit' + (side + 1) + ']';
        notes.forEach(function(note, index) {
            var group = unit.slice(0, -1) + '_Effect' + (index + 1) + ']';
            var on = engine.getValue(unit, 'enabled') && engine.getValue(group, 'loaded') && engine.getValue(group, 'enabled');
            BiteDJNV.sendLED(0x90, note, on ? 127 : 0);
        });
    });
};
BiteDJNV.releasePads = function(deck) {
    Object.keys(BiteDJNV.holds).forEach(function(id) {
        if (id.indexOf('pad' + deck + ':') === 0) { BiteDJNV.hold(id, '', '', false); }
    });
};
BiteDJNV.updatePads = function(deck, force) {
    var group = '[Channel' + deck + ']', mode = BiteDJNV.mode[deck - 1];
    var loaded = engine.getValue(group, 'track_loaded');
    for (var n = 0; n < 8; n++) {
        var available = false, active = !!BiteDJNV.holds['pad' + deck + ':' + n];
        if (mode === 'cue') { available = loaded && engine.getValue(group, 'hotcue_' + (n + 1) + '_enabled'); }
        else if (mode === 'loop' || mode === 'roll') {
            available = !!loaded;
            if (mode === 'loop') { active = !!engine.getValue(group, 'beatloop_' + BiteDJNV.loops[n] + '_enabled'); }
        } else if (mode === 'sampler') {
            available = !!engine.getValue('[Sampler' + (n + 1) + ']', 'track_loaded');
            active = !!engine.getValue('[Sampler' + (n + 1) + ']', 'play_indicator');
        }
        // A pressed cue can be newly created before enabled feedback arrives.
        var code = mode !== 'disabled' && (available || (loaded && active)) ? BiteDJNV.padColors[n] : 0;
        // Active pads blink their selected color; no unverified brightness code.
        if (active && BiteDJNV.meterTicks % 10 >= 5) { code = 0; }
        BiteDJNV.sendLED(0x90 + deck, 0x47 + n, code, force);
    }
};
BiteDJNV.masterLevel = function(value, peak) {
    // [Main] VU is already post software main gain/balance/talkover. Never
    // attenuate it again with a channel fader or the hardware master knob.
    if (typeof value !== 'number' || !isFinite(value) || value <= BiteDJNV.vuSilenceThreshold) { return 0; }
    if (typeof peak === 'number' && isFinite(peak) && peak > 0) { return BiteDJNV.vuPeakLevel; }
    return Math.min(BiteDJNV.vuMaximum, Math.ceil(Math.min(value, 1) * BiteDJNV.vuMaximum));
};
BiteDJNV.updateMasterMeters = function(testLevel) {
    var readings = [];
    ['left', 'right'].forEach(function(side, index) {
        var value = engine.getValue('[Main]', 'vu_meter_' + side);
        var peak = engine.getValue('[Main]', 'peak_indicator_' + side);
        var level = testLevel === undefined ? BiteDJNV.masterLevel(value, peak) : testLevel;
        BiteDJNV.sendLED(0xb0, 0x48 + index, level, level === 0 && BiteDJNV.meterTicks % 20 === 0);
        readings.push([value, peak, level]);
    });
    if (BiteDJNV.meterTicks % 60 === 0) {
        console.info('BiteDJNV master meters [vu,peak,led] left/right=' + JSON.stringify(readings));
    }
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
BiteDJNV.releaseDeck = function(d) {
    var group = '[Channel' + d + ']';
    Object.keys(BiteDJNV.holds).forEach(function(id) {
        if (BiteDJNV.holds[id][0] === group) { BiteDJNV.hold(id, '', '', false); }
    });
    if (engine.isScratching(d)) { engine.scratchDisable(d, true); }
    BiteDJNV.touchStats[d - 1] = null;
    BiteDJNV.shift[d - 1] = false;
};
BiteDJNV.selectDeck = function(d) {
    // Infer a layer from existing deck-channel traffic; no guessed button IDs.
    // Call on deck controls only, never the four-channel mixer or old releases.
    var side = (d - 1) % 2, previous = BiteDJNV.activeDeck[side];
    if (previous === d) { return; }
    if (previous) { BiteDJNV.releaseDeck(previous); }
    BiteDJNV.activeDeck[side] = d;
    BiteDJNV.jogCounters[d - 1] = { low: null, previous: null };
    delete BiteDJNV.bytes['p' + d];
    BiteDJNV.updatePads(d, true);
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
    BiteDJNV.selectDeck(d);
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
    BiteDJNV.selectDeck(d);
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
    // Linear rotation gain also amplifies slow one-count movements. No acceleration.
    if (engine.isScratching(d)) { engine.scratchTick(d, delta * BiteDJNV.scratchSensitivity); }
    else { engine.setValue(group, 'jog', delta * BiteDJNV.jogSensitivity); }
};
BiteDJNV.touch = function(channel, control, value, status, group) {
    var d = BiteDJNV.deck(group);
    if (!d) { return; }
    if (BiteDJNV.pressed(value, status)) { BiteDJNV.selectDeck(d); }
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
                ' travel_ticks=' + stats.travel + ' samples=' + stats.samples + ' largest=' + stats.largest +
                ' sensitivity=' + BiteDJNV.scratchSensitivity);
        }
        BiteDJNV.touchStats[d - 1] = null;
    }
};
BiteDJNV.button = function(channel, control, value, status, group) {
    var d = BiteDJNV.deck(group), down = BiteDJNV.pressed(value, status);
    if (!d) { return; }
    if (down) { BiteDJNV.selectDeck(d); }
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
        BiteDJNV.hold('bend' + d + ':' + control, group,
            control === 0x10 ? 'rate_temp_down' : 'rate_temp_up', down);
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
    BiteDJNV.selectDeck(d);
    var modes = { 26: 'cue', 28: 'loop', 27: 'roll', 29: 'sampler', 30: 'disabled' };
    if (modes[control]) {
        BiteDJNV.releasePads(d);
        BiteDJNV.mode[d - 1] = modes[control];
        BiteDJNV.padModeLEDs(d);
        BiteDJNV.updatePads(d);
    }
};
BiteDJNV.pad = function(channel, control, value, status, group) {
    var d = BiteDJNV.deck(group), n = control - 0x47, down = BiteDJNV.pressed(value, status);
    if (!d || n < 0 || n > 7) { return; }
    if (down) { BiteDJNV.selectDeck(d); }
    var id = 'pad' + d + ':' + n;
    if (!down) { BiteDJNV.hold(id, group, '', false); BiteDJNV.updatePads(d); return; }
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
    var focus = engine.getValue('[Library]', 'focused_widget');
    // Do not move a dialog or search field when using the hardware encoder.
    if (focus !== 2 && focus !== 3) { engine.setValue('[Library]', 'focused_widget', 3); }
    var delta = BiteDJNV.relative(value);
    if (delta) { engine.setValue('[Library]', 'MoveVertical', delta); }
};
BiteDJNV.sidebar = function(channel, control, value, status, group) {
    if (!BiteDJNV.pressed(value, status)) { return; }
    var deck = BiteDJNV.deck(group);
    if (deck) { BiteDJNV.selectDeck(deck); }
    var focus = engine.getValue('[Library]', 'focused_widget');
    if (deck && BiteDJNV.shift[deck - 1] && focus === 2) {
        BiteDJNV.pulse('[Playlist]', 'ToggleSelectedSidebarItem');
    } else if (focus !== 2) {
        engine.setValue('[Sidebar]', 'sidebar_visible', 1);
        engine.setValue('[Library]', 'focused_widget', 2);
    } else {
        // Open the selected folder track table (including mixed folders). Never
        // call GoToItem from the track table: that can load a track implicitly.
        BiteDJNV.pulse('[Library]', 'GoToItem');
    }
};
BiteDJNV.pfl = function(channel, control, value, status, group) {
    if (BiteDJNV.pressed(value, status)) { BiteDJNV.toggle(group, 'pfl'); }
};
BiteDJNV.sendLED = function(status, control, value, force) {
    var id = status + ':' + control;
    if (force || BiteDJNV.ledValues[id] !== value) {
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
BiteDJNV.observeInput = function(channel, control, value, status, group) {
    // Unknown messages are diagnostics only. Never infer D. VIEW from another
    // model or change audio/transport while identifying an unmapped control.
    if ((status & 0xf0) === 0x90 && !value) { return; }
    var id = status + ':' + control, previous = BiteDJNV.inputDiagnostics[id];
    if (BiteDJNV.inputDiagnosticCount >= 600 || (previous && previous.count >= 12)) { return; }
    BiteDJNV.inputDiagnostics[id] = {count: previous ? previous.count + 1 : 1};
    BiteDJNV.inputDiagnosticCount++;
    console.info('BiteDJNV unmapped MIDI status=0x' + status.toString(16) +
        ' control=0x' + control.toString(16) + ' value=' + value +
        ' group=' + group + ' activeDecks=' + JSON.stringify(BiteDJNV.activeDeck));
};
BiteDJNV.meterIdle = function(deck) {
    var group = '[Channel' + deck + ']', position = engine.getValue(group, 'playposition');
    var previous = BiteDJNV.meterMotion[deck - 1];
    var held = Object.keys(BiteDJNV.holds).some(function(id) { return BiteDJNV.holds[id][0] === group; });
    var idle = !engine.getValue(group, 'play') && !engine.isScratching(deck) && !held &&
        previous && Math.abs(position - previous.position) < 0.000000001;
    var ticks = idle ? Math.min(previous.ticks + 1, 6) : 0;
    BiteDJNV.meterMotion[deck - 1] = {position: position, ticks: ticks};
    return ticks >= 6; // 300 ms stationary, paused, with no cue/scratch gesture.
};
BiteDJNV.updateMeters = function() {
    if (BiteDJNV.meterTicks % 2 === 0) {
        for (var padDeck = 1; padDeck <= 4; padDeck++) { BiteDJNV.updatePads(padDeck); }
        BiteDJNV.updateFxLEDs();
    }
    // Optional silent lamp test: 0,1,2,3,4,5,0, each for one second, then normal VU.
    if (BiteDJNV.meterTestTicks < 140) {
        var testLevel = Math.floor(BiteDJNV.meterTestTicks++ / 20) % 6;
        for (var testDeck = 0; testDeck < 4; testDeck++) {
            BiteDJNV.sendLED(0xb0, BiteDJNV.vuAddresses[testDeck], testLevel);
        }
        BiteDJNV.updateMasterMeters(testLevel);
        BiteDJNV.meterTicks++;
        return;
    }
    BiteDJNV.updateMasterMeters();
    var readings = [];
    for (var deck = 1; deck <= 4; deck++) {
        var group = '[Channel' + deck + ']';
        var value = engine.getValue(group, 'vu_meter');
        var fader = engine.getValue(group, 'volume');
        var peak = engine.getValue(group, 'peak_indicator');
        var idle = BiteDJNV.meterIdle(deck);
        var level = idle ? 0 : BiteDJNV.meterLevel(value, fader, peak);
        // Refresh zero once a second, so a dropped clear or an NV layer switch
        // cannot leave a bottom bar latched forever in change-only feedback.
        BiteDJNV.sendLED(0xb0, BiteDJNV.vuAddresses[deck - 1], level,
            level === 0 && BiteDJNV.meterTicks % 20 === 0);
        readings.push([value, fader, peak, level, idle ? 1 : 0]);
    }
    if (++BiteDJNV.meterTicks % 60 === 0) {
        console.info('BiteDJNV meters [vu,fader,peak,led,idle] decks1-4=' + JSON.stringify(readings));
    }
};
BiteDJNV.meterLevel = function(value, fader, peak) {
    if (typeof value !== 'number' || !isFinite(value) || value < 0) { return 0; }
    value = Math.min(value, 1);
    if (BiteDJNV.vuFollowFader) {
        if (typeof fader !== 'number' || !isFinite(fader) || fader <= 0.001) { return 0; }
        // EngineVuMeter exports log10(1 + amplitude * scale), before the fader.
        // Invert/reapply that curve for a visual post-fader estimate; it cannot
        // reconstruct clipped peaks or undo meter smoothing/channel averaging.
        value = Math.log(1 + (Math.pow(10, value) - 1) * fader) / Math.LN10;
    }
    // Report the engine's pre-fader clip flag even if its smoothed VU is lower.
    if (typeof peak === 'number' && isFinite(peak) && peak > 0) { return BiteDJNV.vuPeakLevel; }
    if (value <= BiteDJNV.vuSilenceThreshold) { return 0; }
    return Math.min(BiteDJNV.vuMaximum, Math.ceil(value * BiteDJNV.vuMaximum));
};
BiteDJNV.readSettings = function() {
    var numbers = {
        scratchSensitivity: [2.0, 0.25, 8.0], jogSensitivity: [0.25, 0.05, 2.0],
        vuSilenceThreshold: [0.01, 0.0002, 0.1], vuPeakLevel: [5, 4, 5]
    };
    Object.keys(numbers).forEach(function(name) {
        var spec = numbers[name], value = typeof engine.getSetting === 'function' ? engine.getSetting(name) : undefined;
        BiteDJNV[name] = typeof value === 'number' && isFinite(value) && value >= spec[1] && value <= spec[2] &&
            (name !== 'vuPeakLevel' || Math.floor(value) === value) ? value : spec[0];
    });
    BiteDJNV.padColors = BiteDJNV.padDefaults.map(function(fallback, index) {
        var value = typeof engine.getSetting === 'function' ? engine.getSetting('padColor' + (index + 1)) : undefined;
        return BiteDJNV.padPalette.indexOf(value) >= 0 ? value : fallback;
    });
    ['vuFollowFader', 'vuTest'].forEach(function(name) {
        var value = typeof engine.getSetting === 'function' ? engine.getSetting(name) : undefined;
        BiteDJNV[name] = typeof value === 'boolean' ? value : name === 'vuFollowFader';
    });
};
BiteDJNV.init = function() {
    BiteDJNV.readSettings();
    console.info('BiteDJNV controls v0.5.7: scratchSensitivity=' + BiteDJNV.scratchSensitivity +
        ' jogSensitivity=' + BiteDJNV.jogSensitivity + ' vuFollowFader=' + BiteDJNV.vuFollowFader +
        ' vuSilenceThreshold=' + BiteDJNV.vuSilenceThreshold + ' vuPeakLevel=' + BiteDJNV.vuPeakLevel +
        ' vuTest=' + BiteDJNV.vuTest);
    if (BiteDJNV.meterTimer) { engine.stopTimer(BiteDJNV.meterTimer); }
    BiteDJNV.connections.forEach(function(c) { c.disconnect(); });
    for (var oldDeck = 1; oldDeck <= 4; oldDeck++) { BiteDJNV.releaseDeck(oldDeck); }
    BiteDJNV.activeDeck = [0, 0];
    BiteDJNV.meterMotion = [];
    BiteDJNV.inputDiagnostics = {};
    BiteDJNV.inputDiagnosticCount = 0;
    BiteDJNV.fxPressed = {};
    BiteDJNV.bytes = {};
    BiteDJNV.holds = {};
    BiteDJNV.connections = [];
    BiteDJNV.jogCounters = [];
    BiteDJNV.touchStats = [];
    BiteDJNV.ledValues = {};
    BiteDJNV.meterTicks = 0;
    BiteDJNV.meterTestTicks = BiteDJNV.vuTest ? 0 : 140;
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
    for (var d = 1; d <= 4; d++) { BiteDJNV.releaseDeck(d); }
    BiteDJNV.activeDeck = [0, 0];
    Object.keys(BiteDJNV.ledValues).forEach(function(id) {
        var address = id.split(':'); midi.sendShortMsg(Number(address[0]), Number(address[1]), 0);
    });
    BiteDJNV.jogCounters = []; BiteDJNV.touchStats = []; BiteDJNV.ledValues = {};
};
