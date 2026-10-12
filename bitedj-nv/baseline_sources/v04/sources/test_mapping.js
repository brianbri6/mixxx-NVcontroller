// SPDX-License-Identifier: MIT
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = __dirname;
let passed = 0;

function harness() {
    const values = new Map(), messages = [], scratch = [], jog = [], enabled = new Set(), timers = new Map(), connections = [];
    let nextTimer = 1;
    const identity = (group, key) => group + ':' + key;
    const engine = {
        getValue: (g, k) => values.get(identity(g, k)) || 0,
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
    vm.runInContext(fs.readFileSync(path.join(root, 'payload/BiteDJ-Numark-NV.js'), 'utf8'), context);
    return {nv: context.BiteDJNV, engine, messages, scratch, jog, enabled, timers, connections};
}

function test(name, fn) { fn(); passed++; console.log('PASS ' + name); }

test('golden position vectors, byte rollover and 14-bit rollover', () => {
    const h = harness(), n = h.nv;
    h.enabled.add(1);
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
            assert.deepEqual(deltas, fixture.expected_deltas.filter(v => v !== 0));
            assert.ok(Math.max(...deltas.map(Math.abs)) <= 16);
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
    for (let d = 1; d <= 4; d++) h.engine.setValue('[Channel' + d + ']', 'vu_meter', 0.6);
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

console.log(JSON.stringify({tests: passed, result: 'passed', hardware_tested: false}));
