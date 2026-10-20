// SPDX-License-Identifier: MIT
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../baseline_sources/v04/sources');
const mapping = process.env.NV_MAPPING || path.resolve(__dirname, '../controller/BiteDJ-Numark-NV.js');
let passed = 0;

function harness(settings = {}) {
    const values = new Map(), messages = [], scratch = [], jog = [], enabled = new Set(), timers = new Map(), connections = [];
    let nextTimer = 1;
    const identity = (group, key) => group + ':' + key;
    const engine = {
        getValue: (g, k) => values.has(identity(g, k)) ? values.get(identity(g, k)) : 0,
        getSetting: key => settings[key],
        setValue: (g, k, v) => {
            values.set(identity(g, k), v);
            if (k === 'jog') jog.push([Number(g.match(/\d/)[0]), v]);
            for (const c of connections) if (c.connected && c.group === g && c.key === k) c.fn(v, g, k);
        },
        getParameter: (g, k) => k === 'rate' ? (engine.getValue(g, k) + 1) / 2 : engine.getValue(g, k),
        setParameter: (g, k, v) => engine.setValue(g, k, k === 'rate' ? v * 2 - 1 : v),
        softTakeover: () => {},
        scratchEnable: (d, ...args) => { enabled.add(d); scratch.push(['enable', d, ...args]); },
        scratchDisable: (d, ramp) => { enabled.delete(d); scratch.push(['disable', d, ramp]); },
        isScratching: d => enabled.has(d),
        scratchTick: (d, v) => scratch.push(['tick', d, v]),
        beginTimer: (ms, fn) => { const id = nextTimer++; timers.set(id, {ms, fn}); return id; },
        stopTimer: id => timers.delete(id),
        makeConnection: (group, key, fn) => {
            const c = {group, key, fn, connected: true,
                trigger: () => fn(engine.getValue(group, key), group, key),
                disconnect: () => { c.connected = false; }};
            connections.push(c); return c;
        },
    };
    const context = vm.createContext({engine, midi: {
        sendShortMsg: (...bytes) => messages.push(bytes),
        sendSysexMsg: () => {},
    }, console: {info: () => {}}});
    vm.runInContext(fs.readFileSync(mapping, 'utf8'), context);
    return {nv: context.BiteDJNV, engine, messages, scratch, jog, enabled, timers, connections};
}

function test(name, fn) { fn(); passed++; console.log('PASS ' + name); }

test('golden position vectors, byte rollover and 14-bit rollover', () => {
    const h = harness(), n = h.nv;
    h.enabled.add(1); n.scratchSensitivity = 1;
    for (const position of [126, 127, 128, 129, 128, 127, 0, 16383, 0, 1]) {
        n.jog(1, 0, position % 128, 0xb1, '[Channel1]');
        n.jog(1, 32, Math.floor(position / 128), 0xb1, '[Channel1]');
    }
    assert.deepEqual(h.scratch.map(e => e[2]), [1, 1, 1, -1, -1, -127, -1, 1, 1]);
});

test('incomplete bytes do not move the track', () => {
    const h = harness(), n = h.nv;
    h.enabled.add(1);
    n.jog(1, 32, 50, 0xb1, '[Channel1]');
    n.jog(1, 0, 10, 0xb1, '[Channel1]');
    n.jog(1, 32, 2, 0xb1, '[Channel1]');
    n.jog(1, 32, 50, 0xb1, '[Channel1]');
    assert.equal(h.scratch.length, 0);
});

for (const filename of ['numarknvplatter', 'numarknvplatterwithaudio']) {
    test('capture regression: ' + filename + ', all four deck bindings', () => {
        const fixture = JSON.parse(fs.readFileSync(path.join(root, 'fixtures', filename + '.json')));
        for (let deck = 1; deck <= 4; deck++) {
            const h = harness(); h.enabled.add(deck);
            const group = '[Channel' + deck + ']';
            for (const [control, value] of fixture.rotation_bytes) h.nv.jog(deck, control, value, 0xb0 + deck, group);
            const deltas = h.scratch.filter(e => e[0] === 'tick').map(e => e[2]);
            assert.deepEqual(deltas, fixture.expected_deltas.filter(v => v !== 0).map(v => v * 2));
            assert.ok(Math.max(...deltas.map(Math.abs)) <= 32);
            assert.equal(h.jog.length, 0);
        }
    });
}

test('touch stops immediately, release resumes, vinyl-off selects pitch bend', () => {
    const h = harness(), n = h.nv;
    n.touch(1, 0x5d, 127, 0x91, '[Channel1]');
    assert.equal(h.enabled.has(1), true);
    assert.equal(h.scratch[0][5], 1 / 256);
    assert.equal(h.scratch[0][6], false);
    n.touch(1, 0x5d, 0, 0x81, '[Channel1]');
    assert.equal(h.enabled.has(1), false);
    assert.equal(h.scratch.at(-1)[2], true);
    n.button(1, 0x0c, 127, 0x91, '[Channel1]');
    n.touch(1, 0x5d, 127, 0x91, '[Channel1]');
    for (const raw of [127, 128]) {
        n.jog(1, 0, raw % 128, 0xb1, '[Channel1]');
        n.jog(1, 32, Math.floor(raw / 128), 0xb1, '[Channel1]');
    }
    assert.deepEqual(h.jog, [[1, 0.25]]);
});

test('pitch waits for a pair, hits exactly zero, center LED follows software', () => {
    const h = harness(), n = h.nv;
    n.init(); h.messages.length = 0;
    h.engine.setValue('[Channel1]', 'rate', 0.3);
    n.pitch(1, 1, 64, 0xb1, '[Channel1]');
    assert.equal(h.engine.getValue('[Channel1]', 'rate'), 0.3);
    n.pitch(1, 33, 0, 0xb1, '[Channel1]');
    assert.equal(h.engine.getValue('[Channel1]', 'rate'), 0);
    assert.deepEqual(h.messages.filter(m => m[0] === 0x91 && m[1] === 0x51), [[0x91, 0x51, 0], [0x91, 0x51, 127]]);
    for (const [raw, expected] of [[0, -1], [8192, 0], [16383, 1]]) {
        n.pitch(1, 1, Math.floor(raw / 128), 0xb1, '[Channel1]');
        n.pitch(1, 33, raw % 128, 0xb1, '[Channel1]');
        assert.equal(h.engine.getValue('[Channel1]', 'rate'), expected);
    }
});

test('meter output is bounded, change-only and stopped at shutdown', () => {
    const h = harness(), n = h.nv;
    n.init(); assert.equal(h.timers.size, 1); assert.equal([...h.timers.values()][0].ms, 50);
    h.messages.length = 0;
    for (let d = 1; d <= 4; d++) {
        h.engine.setValue('[Channel' + d + ']', 'volume', 1);
        h.engine.setValue('[Channel' + d + ']', 'vu_meter', 0.6);
    }
    n.updateMeters(); assert.equal(h.messages.length, 4);
    n.updateMeters(); assert.equal(h.messages.length, 4);
    for (const m of h.messages) assert.equal(m[2], 3);
    h.engine.setValue('[Channel1]', 'vu_meter', 2); n.updateMeters(); assert.equal(h.messages.at(-1)[2], 4);
    h.engine.setValue('[Channel1]', 'vu_meter', NaN); n.updateMeters(); assert.equal(h.messages.at(-1)[2], 0);
    n.shutdown(); assert.equal(h.timers.size, 0); assert.equal(h.connections.filter(c => c.connected).length, 0);
});

test('PFL, pad mode and vinyl feedback survives reinitialization', () => {
    const h = harness(), n = h.nv;
    n.init(); h.messages.length = 0;
    h.engine.setValue('[Channel1]', 'pfl', 1);
    assert.deepEqual(h.messages.at(-1), [0x90, 0x35, 127]);
    n.padMode(1, 0x1c, 127, 0x91, '[Channel1]');
    assert.equal(n.mode[0], 'loop');
    assert.ok(h.messages.some(m => m[0] === 0x91 && m[1] === 0x1c && m[2] === 127));
    n.init(); assert.equal(h.timers.size, 1); assert.equal(h.connections.filter(c => c.connected).length, 24);
    n.shutdown();
});

function rotation(h, deck, position) {
    const group = '[Channel' + deck + ']';
    h.nv.jog(deck, 0, position % 128, 0xb0 + deck, group);
    h.nv.jog(deck, 32, Math.floor(position / 128), 0xb0 + deck, group);
}

test('returning to either physical platter layer acquires a fresh baseline', () => {
    for (const side of [1, 2]) {
        const h = harness();
        rotation(h, side, 100); rotation(h, side, 101);
        rotation(h, side + 2, 900); rotation(h, side + 2, 901);
        rotation(h, side, 950); rotation(h, side, 951);
        assert.deepEqual(h.jog, [[side, 0.25], [side + 2, 0.25], [side, 0.25]]);
    }
});

test('layer change drops incomplete pitch bytes and releases only that side', () => {
    const h = harness(), n = h.nv;
    n.touch(1, 0x5d, 127, 0x91, '[Channel1]');
    n.button(1, 0x20, 127, 0x91, '[Channel1]');
    n.button(1, 0x11, 127, 0x91, '[Channel1]');
    n.button(2, 0x20, 127, 0x92, '[Channel2]');
    n.pitch(1, 1, 127, 0xb1, '[Channel1]');
    rotation(h, 3, 900);
    assert.equal(h.enabled.has(1), false);
    assert.equal(h.engine.getValue('[Channel1]', 'cue_default'), 0);
    assert.equal(h.engine.getValue('[Channel1]', 'rate_temp_up'), 0);
    assert.equal(h.engine.getValue('[Channel2]', 'cue_default'), 1);
    n.pitch(1, 33, 127, 0xb1, '[Channel1]');
    assert.equal(h.engine.getValue('[Channel1]', 'rate'), 0);
});

test('old-layer releases and four-channel mixer controls do not change active layer', () => {
    const h = harness(), n = h.nv;
    rotation(h, 3, 900);
    n.button(1, 0x20, 0, 0x81, '[Channel1]');
    n.pad(1, 0x47, 0, 0x81, '[Channel1]');
    n.touch(1, 0x5d, 0, 0x81, '[Channel1]');
    n.pfl(0, 0x35, 127, 0x90, '[Channel1]');
    n.mixer(0, 0x08, 80, 0xb0, '[Channel1]');
    rotation(h, 3, 901);
    assert.deepEqual(h.jog, [[3, 0.25]]);
});

test('pad mode changes and layer switches release the original held roll', () => {
    const h = harness(), n = h.nv;
    n.padMode(1, 0x1b, 127, 0x91, '[Channel1]');
    n.pad(1, 0x47, 127, 0x91, '[Channel1]');
    n.padMode(3, 0x1a, 127, 0x93, '[Channel3]');
    assert.equal(h.engine.getValue('[Channel1]', 'beatlooproll_0.125_activate'), 0);
    n.pad(3, 0x47, 0, 0x83, '[Channel3]');
    assert.equal(Object.keys(n.holds).length, 0);
});

test('reinitialization and shutdown release scratch and momentary controls', () => {
    for (const action of ['init', 'shutdown']) {
        const h = harness(), n = h.nv;
        n.init();
        n.touch(1, 0x5d, 127, 0x91, '[Channel1]');
        n.button(1, 0x20, 127, 0x91, '[Channel1]');
        n.button(1, 0x10, 127, 0x91, '[Channel1]');
        n[action]();
        assert.equal(h.enabled.size, 0);
        assert.equal(h.engine.getValue('[Channel1]', 'cue_default'), 0);
        assert.equal(h.engine.getValue('[Channel1]', 'rate_temp_down'), 0);
    }
});

test('small slow scratch movements scale both ways, wrap, and leave pitch bend independent', () => {
    for (const gain of [0.25, 1, 2, 4, 8]) {
        const h = harness({scratchSensitivity: gain, jogSensitivity: 0.5});
        h.nv.init(); h.nv.touch(1, 0x5d, 127, 0x91, '[Channel1]');
        for (const raw of [16383, 0, 1, 0, 16383]) rotation(h, 1, raw);
        assert.deepEqual(h.scratch.filter(x => x[0] === 'tick').map(x => x[2]), [gain, gain, -gain, -gain]);
        h.nv.touch(1, 0x5d, 0, 0x81, '[Channel1]');
        rotation(h, 1, 0);
        assert.deepEqual(h.jog, [[1, 0.5]]);
    }
});

test('invalid tuning values fall back without freezing or accelerating the platter', () => {
    for (const value of [undefined, null, '4', NaN, Infinity, -1, 0, 9]) {
        const h = harness({scratchSensitivity: value, vuPeakLevel: 4.5});
        h.nv.init();
        assert.equal(h.nv.scratchSensitivity, 2);
        assert.equal(h.nv.vuPeakLevel, 5);
    }
});

test('silence and bottomed fader clear green and held peak; clip uses candidate red', () => {
    const h = harness(), n = h.nv;
    n.init();
    for (const value of [0, 0.0001, 0.001, 0.009, NaN, Infinity, -1]) {
        assert.equal(n.meterLevel(value, 1, 0), 0);
    }
    assert.equal(n.meterLevel(0.5, 1, 0), 2);
    assert.equal(n.meterLevel(0.5, 0.1, 0), 1);
    assert.equal(n.meterLevel(0.5, 0, 1), 0);
    assert.equal(n.meterLevel(1, 0.001, 1), 0);
    assert.equal(n.meterLevel(0.3, 1, 1), 5);
    assert.equal(n.meterLevel(1, 1, 0), 4); // Full fader alone does not mean clipping.
    assert.equal(n.meterLevel(0.3, 1, NaN), 2);
    n.vuFollowFader = false;
    assert.equal(n.meterLevel(0.5, 0, 0), 2);
    assert.equal(n.meterLevel(0.5, 0, 1), 5);
    n.vuPeakLevel = 4;
    assert.equal(n.meterLevel(0.5, 0, 1), 4);
});

test('optional lamp sequence reaches five without touching audio and returns to meters', () => {
    const h = harness({vuTest: true}), n = h.nv;
    n.init();
    for (let i = 1; i < 140; i++) n.updateMeters();
    const levels = h.messages.filter(m => m[0] === 0xb0 && m[1] === 0x4b).map(m => m[2]);
    assert.deepEqual(levels, [0, 1, 2, 3, 4, 5, 0]);
    h.engine.setValue('[Channel1]', 'volume', 1);
    h.engine.setValue('[Channel1]', 'vu_meter', 0.5);
    n.updateMeters();
    assert.deepEqual(h.messages.filter(m => m[0] === 0xb0 && m[1] === 0x4b).at(-1), [0xb0, 0x4b, 2]);
    assert.equal(h.engine.getValue('[Channel1]', 'play'), 0);
    assert.equal(h.enabled.size, 0);
    n.shutdown(); assert.equal(h.timers.size, 0);
});

test('paused stationary decks clear a stuck meter and refresh zero, but scratching and cue remain live', () => {
    const h = harness(), n = h.nv;
    n.init();
    h.engine.setValue('[Channel1]', 'volume', 1);
    h.engine.setValue('[Channel1]', 'vu_meter', 0.4);
    h.engine.setValue('[Channel1]', 'peak_indicator', 1);
    for (let i = 0; i < 10; i++) n.updateMeters();
    const meter = () => h.messages.filter(m => m[0] === 0xb0 && m[1] === 0x4b);
    assert.equal(meter().at(-1)[2], 0);
    const cleared = meter().length;
    for (let i = 0; i < 20; i++) n.updateMeters();
    assert.equal(meter().length, cleared + 1);
    n.touch(1, 0x5d, 127, 0x91, '[Channel1]'); n.updateMeters();
    assert.equal(meter().at(-1)[2], 5);
    n.touch(1, 0x5d, 0, 0x81, '[Channel1]');
    n.button(1, 0x20, 127, 0x91, '[Channel1]');
    for (let i = 0; i < 10; i++) n.updateMeters();
    assert.equal(meter().at(-1)[2], 5);
    n.button(1, 0x20, 0, 0x81, '[Channel1]');
    for (let i = 0; i < 10; i++) {
        h.engine.setValue('[Channel1]', 'playposition', i / 1000); n.updateMeters();
    }
    assert.equal(meter().at(-1)[2], 5);
    h.engine.setValue('[Channel1]', 'volume', 0); n.updateMeters();
    assert.equal(meter().at(-1)[2], 0);
    h.engine.setValue('[Channel1]', 'volume', 1);
    h.engine.setValue('[Channel1]', 'play', 1);
    for (let i = 0; i < 10; i++) n.updateMeters();
    assert.equal(meter().at(-1)[2], 5);
});

test('unmapped diagnostics are bounded and never send MIDI or change transport', () => {
    const h = harness(), n = h.nv;
    for (let i = 0; i < 1000; i++) n.observeInput(1, 0x7e, 127, 0x91, '[Channel1]');
    assert.equal(n.inputDiagnosticCount, 12);
    n.observeInput(1, 0x7e, 0, 0x91, '[Channel1]');
    assert.equal(n.inputDiagnosticCount, 12);
    for (let cc = 0; cc < 128; cc++) {
        for (let i = 0; i < 12; i++) n.observeInput(0, cc, 127, 0xb0, '[Master]');
    }
    assert.equal(n.inputDiagnosticCount, 600);
    assert.equal(h.messages.length, 0);
    assert.equal(h.scratch.length, 0);
    assert.equal(h.engine.getValue('[Channel1]', 'play'), 0);
});

test('FX banks address three slots, route selected decks, preserve mix, debounce and release', () => {
    const h = harness(), n = h.nv;
    n.init();
    for (const [side, notes] of [[0,[15,16,17]], [1,[19,20,21]]]) {
        const deck = side + 3, unit = '[EffectRack1_EffectUnit' + (side+1) + ']';
        n.selectDeck(deck); h.engine.setValue(unit, 'mix', 0.35);
        for (let slot=1; slot<=3; slot++) {
            const g = unit.slice(0,-1) + '_Effect' + slot + ']', note=notes[slot-1];
            h.engine.setValue(g,'loaded',1);
            n.fxButton(0,note,127,0x90);
            assert.equal(h.engine.getValue(g,'enabled'),1);
            assert.equal(h.engine.getValue(unit,'group_[Channel'+deck+']_enable'),1);
            assert.equal(h.engine.getValue(unit,'mix'),0.35);
            n.fxButton(0,note,127,0x90); assert.equal(h.engine.getValue(g,'enabled'),1);
            n.fxButton(0,note,127,0x80); assert.equal(h.engine.getValue(g,'enabled'),1);
            n.fxButton(0,note,127,0x90); assert.equal(h.engine.getValue(g,'enabled'),0);
            n.fxButton(0,note,0,0x90);
        }
    }
});
test('FX shift selects effects and first knob controls wet/dry; other knobs adjust slot meta', () => {
    const h=harness(), n=h.nv, writes=[], set=h.engine.setValue;
    h.engine.setValue=(...v)=>{writes.push(v);set(...v);};
    n.init(); assert.equal(writes.length,0); // No startup DSP/routing mutation.
    for (const [side, knobs, notes] of [[0,[4,5,6],[15,16,17]],[1,[73,74,75],[19,20,21]]]) {
        const unit='[EffectRack1_EffectUnit'+(side+1)+']';
        knobs.forEach((cc,i)=>{
            const g=unit.slice(0,-1)+'_Effect'+(i+1)+']';
            n.fxKnob(0,cc,127,0xb0); assert.equal(h.engine.getValue(g,'meta'),1);
            n.fxKnob(0,cc,0,0xb0); assert.equal(h.engine.getValue(g,'meta'),0);
            n.shift[side]=true;
            n.fxButton(0,notes[i],127,0x90); n.fxButton(0,notes[i],0,0x80);
            assert.ok(writes.some(x=>x[0]===g&&x[1]==='next_effect'&&x[2]===1));
            n.fxKnob(0,cc,64,0xb0); assert.equal(h.engine.getValue(g,'meta'),0);
            assert.equal(h.engine.getValue(unit,'mix'),64/127);
            n.shift[side]=false;
        });
    }
    n.fxButton(0,15,127,0x90); // Empty slot loads on explicit press.
    assert.equal(h.engine.getValue('[EffectRack1_EffectUnit1_Effect1]','enabled'),1);
});
test('FX lights follow loaded/enabled state and turn off on shutdown', () => {
    const h=harness(), n=h.nv, u='[EffectRack1_EffectUnit1]', g=u.slice(0,-1)+'_Effect2]';
    n.init(); h.engine.setValue(u,'enabled',1); h.engine.setValue(g,'loaded',1); h.engine.setValue(g,'enabled',1);
    n.updateFxLEDs(); assert.deepEqual(h.messages.at(-1),[0x90,16,127]);
    h.engine.setValue(g,'loaded',0); n.updateFxLEDs(); assert.deepEqual(h.messages.at(-1),[0x90,16,0]);
    n.shutdown(); assert.ok(h.messages.filter(m=>m[0]===0x90&&m[1]===16).at(-1)[2]===0);
});
test('pad colors follow cue availability, loop state and sampler playback; silence unloaded pads', () => {
    const h=harness({padColor1:3}),n=h.nv,g='[Channel1]'; n.init();
    const led=()=>h.messages.filter(m=>m[0]===0x91&&m[1]===0x47).at(-1)[2];
    assert.equal(led(),0);
    h.engine.setValue(g,'track_loaded',1); h.engine.setValue(g,'hotcue_1_enabled',1); n.updatePads(1); assert.equal(led(),3);
    h.engine.setValue(g,'track_loaded',0); n.updatePads(1); assert.equal(led(),0);
    h.engine.setValue(g,'track_loaded',1); n.padMode(1,28,127,0x91,g); assert.equal(led(),3);
    h.engine.setValue(g,'beatloop_0.125_enabled',1); n.meterTicks=5; n.updatePads(1); assert.equal(led(),0);
    n.meterTicks=10; n.updatePads(1); assert.equal(led(),3);
    n.padMode(1,27,127,0x91,g); n.pad(1,0x47,127,0x91,g);
    assert.equal(h.engine.getValue(g,'beatlooproll_0.125_activate'),1);
    n.padMode(1,29,127,0x91,g); assert.equal(h.engine.getValue(g,'beatlooproll_0.125_activate'),0);
    assert.equal(led(),0); h.engine.setValue('[Sampler1]','track_loaded',1); n.updatePads(1); assert.equal(led(),3);
    h.engine.setValue('[Sampler1]','play_indicator',1); n.meterTicks=5; n.updatePads(1); assert.equal(led(),0);
    n.padMode(1,30,127,0x91,g); n.meterTicks=10; n.updatePads(1); assert.equal(led(),0);
});
test('pad palette rejects uncaptured values and refreshes deck layers with captured output only', () => {
    const h=harness({padColor1:0,padColor2:5,padColor3:'52',padColor4:Infinity}),n=h.nv; n.init();
    assert.deepEqual(Array.from(n.padColors),[0,52,48,21,6,3,52,21]);
    h.engine.setValue('[Channel3]','track_loaded',1); h.engine.setValue('[Channel3]','hotcue_2_enabled',1); n.selectDeck(3);
    assert.deepEqual(h.messages.filter(m=>m[0]===0x93&&m[1]===0x48).at(-1),[0x93,0x48,52]);
    const evidence=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../docs/control-feedback-evidence.json')));
    const extra=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../docs/HANDOFF_EVIDENCE.json'))).pad_palette;
    const captured=[...new Set(extra.concat(evidence.records.filter(r=>r.category==='pad_palette').flatMap(r=>Object.keys(r.counts).map(Number))))].sort((a,b)=>a-b);
    assert.deepEqual(Array.from(n.padPalette),captured);
    for(const m of h.messages.filter(m=>m[0]>=0x91&&m[0]<=0x94&&m[1]>=0x47&&m[1]<=0x4e)) assert.ok(n.padPalette.includes(m[2]));
    n.shutdown(); assert.equal(h.messages.filter(m=>m[0]===0x93&&m[1]===0x48).at(-1)[2],0);
});
test('stereo master meters use Main post-gain levels, clear silence/latched peaks, and include lamp test', () => {
    const h=harness(),n=h.nv; n.init();
    h.engine.setValue('[Master]','vu_meter_left',1); h.engine.setValue('[Channel1]','volume',0);
    h.engine.setValue('[Main]','vu_meter_left',0.6); h.engine.setValue('[Main]','vu_meter_right',0.1); n.updateMasterMeters();
    const levels=()=>[0x48,0x49].map(cc=>h.messages.filter(m=>m[0]===0xb0&&m[1]===cc).at(-1)[2]);
    assert.deepEqual(levels(),[3,1]);
    h.engine.setValue('[Main]','peak_indicator_right',1); n.updateMasterMeters(); assert.deepEqual(levels(),[3,5]);
    h.engine.setValue('[Main]','vu_meter_left',NaN); h.engine.setValue('[Main]','vu_meter_right',0); n.updateMasterMeters(); assert.deepEqual(levels(),[0,0]);
    const lamp=harness({vuTest:true}); lamp.nv.init(); for(let i=1;i<140;i++) lamp.nv.updateMeters();
    for(const cc of [0x48,0x49]) assert.deepEqual(lamp.messages.filter(m=>m[0]===0xb0&&m[1]===cc).map(m=>m[2]),[0,1,2,3,4,5,0]);
});
test('browser enters sidebar leaves, returns to folders and never implicitly loads from track table', () => {
    const h=harness(),n=h.nv,writes=[],set=h.engine.setValue;
    h.engine.setValue=(...v)=>{writes.push(v);set(...v);};
    h.engine.setValue('[Library]','focused_widget',3);
    n.sidebar(1,6,127,0x91,'[Channel1]'); assert.equal(h.engine.getValue('[Library]','focused_widget'),2);
    assert.ok(!writes.some(v=>v[1]==='GoToItem'));
    n.sidebar(1,6,127,0x91,'[Channel1]'); assert.ok(writes.some(v=>v[1]==='GoToItem'&&v[2]===1));
    writes.length=0; n.shift[0]=true; n.sidebar(1,6,127,0x91,'[Channel1]'); assert.ok(!writes.some(v=>v[1]==='GoToItem'));
    assert.ok(writes.some(v=>v[0]==='[Playlist]'&&v[1]==='ToggleSelectedSidebarItem'&&v[2]===1));
    n.browse(0,3,1); assert.equal(h.engine.getValue('[Library]','focused_widget'),2); assert.equal(h.engine.getValue('[Library]','MoveVertical'),1);
    h.engine.setValue('[Library]','focused_widget',0); n.browse(0,3,127); assert.equal(h.engine.getValue('[Library]','focused_widget'),3); assert.equal(h.engine.getValue('[Library]','MoveVertical'),-1);
});

test('learned Sel push uses mixed-folder navigation and Shift expansion without loading', () => {
    const h=harness(), n=h.nv, e=h.engine, calls=[];
    const set=e.setValue; e.setValue=(g,k,v)=>{calls.push([g,k,v]);set(g,k,v);};
    const press=()=>n.observeInput(1,7,127,0x91,'[Channel1]');
    const release=()=>n.observeInput(1,7,0,0x81,'[Channel1]');
    e.setValue('[Library]','focused_widget',2); press(); press();
    assert.equal(calls.filter(c=>c[1]==='GoToItem'&&c[2]===1).length,1);
    release(); n.shift[0]=true; press(); release();
    assert.ok(calls.some(c=>c[1]==='ToggleSelectedSidebarItem'&&c[2]===1));
    e.setValue('[Library]','focused_widget',3); press(); release();
    assert.equal(e.getValue('[Sidebar]','sidebar_visible'),1);
    assert.equal(e.getValue('[Library]','focused_widget'),2);
    assert.ok(!calls.some(c=>c[1]==='LoadSelectedTrack'));
});

test('learned Slip handles release, duplicate down and layer return', () => {
    const h=harness(), n=h.nv, e=h.engine;
    n.observeInput(1,4,127,0x91,'[Channel1]');
    n.observeInput(1,4,127,0x91,'[Channel1]');
    assert.equal(e.getValue('[Channel1]','slip_enabled'),1);
    n.observeInput(1,4,0,0x81,'[Channel1]');
    assert.equal(e.getValue('[Channel1]','slip_enabled'),1);
    n.selectDeck(3); n.selectDeck(1);
    n.observeInput(1,4,127,0x91,'[Channel1]');
    assert.equal(e.getValue('[Channel1]','slip_enabled'),0);
});

test('channel and master FX A+B route independently and honor explicit unroute', () => {
    const h=harness(), n=h.nv, e=h.engine, a='[EffectRack1_EffectUnit1]', b='[EffectRack1_EffectUnit2]';
    e.setValue(a,'mix',.37);
    function press(note) { n.observeInput(0,note,127,0x90,'[Master]'); n.observeInput(0,note,0,0x80,'[Master]'); }
    press(0x24); press(0x25);
    assert.equal(e.getValue(a,'group_[Channel1]_enable'),1);
    assert.equal(e.getValue(b,'group_[Channel1]_enable'),1);
    press(0x2a); press(0x2b);
    assert.equal(e.getValue(a,'group_[Main]_enable'),1);
    assert.equal(e.getValue(b,'group_[Main]_enable'),1);
    press(0x24); press(0x2a);
    n.fxButton(0,0x0f,127,0x90);
    assert.equal(e.getValue(a,'group_[Channel1]_enable'),0);
    assert.equal(e.getValue(a,'mix'),.37);
    assert.ok(h.messages.some(m=>m[0]===0x90&&m[1]===0x2a&&m[2]===0));
});

test('reverse and pitch-bend feedback clears on layer change and follows toggles', () => {
    const h=harness(), n=h.nv;
    n.button(1,0x0b,127,0x91,'[Channel1]');
    n.button(1,0x10,127,0x91,'[Channel1]');
    n.selectDeck(3);
    assert.equal(n.ledValues['145:11'],0);
    assert.equal(n.ledValues['145:16'],0);
    n.selectDeck(1); n.shift[0]=true;
    n.button(1,0x0b,127,0x91,'[Channel1]');
    n.button(1,0x0b,127,0x91,'[Channel1]');
    assert.equal(n.ledValues['145:11'],0);
});

test('D.VIEW and Beat encoder inputs never echo unverified output commands', () => {
    const h=harness(), n=h.nv;
    for (let cc of [0x61,0x62]) for(let value=0;value<=2;value++)n.observeInput(0,cc,value,0xb0,'[Master]');
    for (let cc of [0x48,0x4c]) for(let value of [1,127])n.observeInput(0,cc,value,0xb0,'[Master]');
    assert.deepEqual(Array.from(n.nvView),[2,2]);
    assert.equal(h.messages.length,0);
    assert.equal(h.engine.getValue('[Main]','gain'),0);
});

test('Beatkeeper position is bounded, tempo relative, active-layer aware and cached', () => {
    const h=harness(), n=h.nv, e=h.engine;
    for (let d of [1,2,3]) {e.setValue('[Channel'+d+']','track_loaded',1);e.setValue('[Channel'+d+']','bpm',120);}
    n.updateBeatkeeper(); assert.deepEqual(h.messages.at(-1),[0xb0,0x47,6]);
    const count=h.messages.length; n.updateBeatkeeper(); assert.equal(h.messages.length,count);
    e.setValue('[Channel3]','bpm',150); n.selectDeck(3);
    assert.equal(n.ledValues['176:71'],1);
    assert.equal(n.beatkeeperPosition(80,120,.1,.5),11);
    assert.equal(n.beatkeeperPosition(NaN,120,.1,.5),0);
    n.beatkeeperEnabled=false; n.updateBeatkeeper(); assert.equal(n.ledValues['176:71'],0);
});

test('Cue Blend uses one 7-bit value and ignores speculative fine byte', () => {
    const h=harness();
    for(const value of [0,64,127]) {
        h.nv.mixer(0,0x12,value,0xb0,'[Master]');
        assert.equal(h.engine.getValue('[Main]','headMix'),value/127);
    }
    h.nv.mixer(0,0x32,0,0xb0,'[Master]');
    assert.equal(h.engine.getValue('[Main]','headMix'),1);
});

console.log(JSON.stringify({tests: passed, result: 'passed', hardware_tested: false}));
