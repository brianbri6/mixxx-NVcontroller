# SPDX-License-Identifier: MIT
"""Run with python3 -m nvdisplay.service. Full mode sends text/numeric fields and both waveforms.

Only --mode full enables the provisional scrolling waveform interpretation.
No firmware commands, packet replay, USB driver manipulation or audio opens.
"""
import argparse
import copy
import fcntl
import json
import math
import os
from pathlib import Path
import signal
import socket
import time

from . import __version__, protocol
from .transport import AlsaOutput, OutputQueue, discover
from .telemetry import TransportTelemetry

SOCKET_PATH = '/tmp/bitedj-nv/state.sock'
# All 480 columns exported by the native producer. Fill around the playhead
# first, then the edges; a tile is 30 columns / 125 ms. Keep the byte cap.
DETAIL_OFFSETS = (0, 1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6, -6, 7, 8, 9)


def validate(data):
    if not isinstance(data, dict) or data.get('schema') != 1 or data.get('source') != 'native':
        raise ValueError('Unsupported state schema/source')
    if not isinstance(data.get('session'), str) or not 1 <= len(data['session']) <= 128:
        raise ValueError('Invalid session')
    clock = data.get('clock_ms')
    if type(clock) not in (int, float) or not math.isfinite(clock) or not 0 <= clock < 2**53:
        raise ValueError('Invalid clock')
    decks = data.get('decks')
    if not isinstance(decks, list) or len(decks) > 4:
        raise ValueError('Invalid deck list')
    seen = set()
    for deck in decks:
        if not isinstance(deck, dict):
            raise ValueError('Invalid deck')
        protocol.selector(deck.get('deck'))
        if deck['deck'] in seen:
            raise ValueError('Duplicate deck')
        seen.add(deck['deck'])
        if type(deck.get('loaded')) is not bool or type(deck.get('generation')) is not int:
            raise ValueError('Invalid deck state')
        for name in ('title', 'artist', 'key'):
            if name in deck and (not isinstance(deck[name], str) or len(deck[name]) > 4096):
                raise ValueError('Invalid text field')
        for name in ('original_bpm', 'duration_ms', 'position_ms', 'bpm', 'pitch_percent',
                     'range_percent', 'beat_distance', 'detail_start_ms'):
            value = deck.get(name, 0)
            if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 2**32:
                raise ValueError('Invalid numeric field')
        if deck.get('overview_ready'):
            protocol.decode_peaks(deck.get('overview'), 240)
        if deck.get('detail_ready'):
            protocol.decode_peaks(deck.get('detail'), 480)
            if deck.get('columns_per_second') != 240 or deck.get('detail_start_ms', 0) % 125:
                raise ValueError('Invalid detail timing')
    effects = data.get('effects', [])
    if not isinstance(effects, list) or len(effects) > 2:
        raise ValueError('Invalid effects')
    units = set()
    for unit in effects:
        if not isinstance(unit, dict) or type(unit.get('unit')) is not int or unit['unit'] not in (1, 2) or unit['unit'] in units:
            raise ValueError('Invalid effect unit')
        units.add(unit['unit'])
        slots = unit.get('slots')
        if not isinstance(slots, list) or len(slots) > 3:
            raise ValueError('Invalid effect slots')
        for slot in slots:
            if not isinstance(slot, dict) or not isinstance(slot.get('name'), str) or len(slot['name']) > 128:
                raise ValueError('Invalid effect name')
            value = slot.get('meta_percent')
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100):
                raise ValueError('Invalid effect value')
    if 'browser' in data:
        browser = data['browser']
        if not isinstance(browser, dict) or type(browser.get('available')) is not bool:
            raise ValueError('Invalid browser state')
        if not isinstance(browser.get('heading'), str) or len(browser['heading']) > 128:
            raise ValueError('Invalid browser heading')
        folders, tracks = browser.get('folders'), browser.get('tracks')
        if not isinstance(folders, list) or len(folders) > 8 or any(not isinstance(v, str) or len(v) > 128 for v in folders):
            raise ValueError('Invalid folders')
        if not isinstance(tracks, list) or len(tracks) > 7:
            raise ValueError('Invalid browser rows')
        for track in tracks:
            if not isinstance(track, dict):
                raise ValueError('Invalid browser track')
            for key, limit in (('title', 256), ('artist', 128)):
                if not isinstance(track.get(key), str) or len(track[key]) > limit:
                    raise ValueError('Invalid browser text')
            bpm = track.get('bpm')
            if bpm is not None and (type(bpm) not in (int, float) or not math.isfinite(bpm) or not 0 <= bpm <= 2**32):
                raise ValueError('Invalid browser BPM')
        for key, low, high in (('selected_folder', -1, len(folders)-1), ('selected_row', -1, len(tracks)-1),
                               ('first_row', 0, 2**31-1), ('total_rows', 0, 2**31-1)):
            value = browser.get(key)
            if type(value) is not int or not low <= value <= high:
                raise ValueError('Invalid browser cursor/count')
    return data


class Screen:
    def __init__(self, side, output, now, mode='info', browser_view='preserve', transport_hz=60):
        self.side, self.mode = side, mode
        self.numbers = (1, 3) if side == 'left' else (2, 4)
        self.queue = OutputQueue(output, now)
        self.acked = {}
        self.states = {}
        self.last_received = now
        self.session = None
        self.stale = False
        self.next_stale_refresh = now
        self.last_clock = None
        self.detail_records = {}  # cache expensive rasterization by deck/time/peaks
        self.coverage = {}
        self.browser_view = browser_view
        self.auxiliary = None
        self.aux_records = []
        self.aux_status = {}
        self.next_auxiliary = now
        self.telemetry = TransportTelemetry(transport_hz)
        for i, packet in enumerate(protocol.startup(side)):
            self.queue.put(('startup', i), packet, now, ttl=10, priority=5)
        visibility = protocol.browser_visibility(side, browser_view)
        if visibility is not None:
            self.queue.put(('startup', 'browser'), visibility, now, ttl=10, priority=5)

    def record(self, deck, kind, index, raw, now, ttl=2, priority=None, packet=None):
        key = (deck, kind, index)
        if packet is None:
            packet = protocol.encode(self.side, kind, raw)
        if priority is None:
            priority = 4 if kind == 5 else (3 if kind in (1, 4) else 0)
        if self.queue.pending_data(key) == packet:
            self.queue.prioritize(key, priority)
            return False
        # A -> queued B -> A must cancel B. If B is already partially written,
        # finish its framing, suppress its ACK, then send corrective A.
        self.queue.invalidate(lambda candidate: candidate == key)
        if self.queue.contains(key):
            # A partial conflicting record will change the hardware even though
            # its ACK is suppressed. If the corrective record later expires,
            # an earlier ACK must not prevent retrying the desired value.
            self.acked.pop(key, None)
        if self.acked.get(key) == packet and not self.queue.contains(key):
            return False
        def completed():
            self.acked[key] = packet
        self.queue.put(key, packet, now, ttl, completed, priority)
        return True

    def invalidate(self, deck, detail_only=False):
        def matches(key):
            return key[0] == deck and (not detail_only or key[1] == 9)
        self.queue.invalidate(matches)
        for key in list(self.acked):
            if matches(key):
                del self.acked[key]
        for key in list(self.detail_records):
            if key[0] == deck:
                del self.detail_records[key]

    def update_deck(self, deck, clock, now):
        number = deck['deck']
        previous = self.states.get(number)
        generation = (deck['generation'], deck['loaded'])
        changed = previous is None or previous['generation'] != generation
        position = deck.get('position_ms', 0) if deck['loaded'] else 0
        discontinuity = self.telemetry.observe(deck, clock, now)
        if changed:
            self.invalidate(number)
        elif discontinuity:
            self.invalidate(number, detail_only=True)
        if not deck['loaded']:
            deck = {'deck': number, 'loaded': False, 'generation': deck['generation']}
        self.record(number, 1, 0, protocol.metadata(deck), now)
        self.record(number, 4, 0, protocol.numeric(deck), now)
        if self.mode in ('overview', 'full'):
            overview = (protocol.decode_peaks(deck['overview'], 240)
                        if deck.get('overview_ready') else bytes(960))
            if previous is None or previous.get('overview') != overview:
                records = protocol.overview(number, overview)
            else:
                records = previous['overview_records']
            for i, raw in enumerate(records):
                self.record(number, 7, i, raw, now)
        else:
            overview, records = None, []
        if self.mode == 'full':
            data = protocol.decode_peaks(deck['detail'], 480) if deck.get('detail_ready') else None
            start = int(deck.get('detail_start_ms', 0))
            center = int(position // 125) * 125
            wanted = {center + n*125 for n in DETAIL_OFFSETS if 0 <= center+n*125 < 2**32}
            # Prune unsent and acknowledged tiles outside the current window.
            self.queue.invalidate(lambda k: k[0] == number and k[1] == 9 and k[2] not in wanted)
            for key in list(self.acked):
                if key[0] == number and key[1] == 9 and key[2] not in wanted:
                    del self.acked[key]
            for key in list(self.detail_records):
                if key[0] == number and key[1] not in wanted:
                    del self.detail_records[key]
            added = 0
            for n in DETAIL_OFFSETS:
                timestamp = center + n*125
                if timestamp not in wanted:
                    continue
                column = (timestamp-start)*240//1000
                peaks = data[column*4:(column+30)*4] if data is not None and 0 <= column <= 450 else bytes(120)
                cache_key = (number, timestamp)
                cached = self.detail_records.get(cache_key)
                if cached is None or cached[0] != peaks:
                    cached = (peaks, protocol.detail(number, timestamp, peaks))
                    self.detail_records[cache_key] = cached
                if self.record(number, 9, timestamp, cached[1], now, ttl=2,
                               priority=1 if -3 <= n <= 4 else 0):
                    added += 1
                    if added == 2:
                        break
        else:
            wanted = set()
        self.coverage[number] = {
            'loaded': deck['loaded'], 'generation': deck['generation'],
            'overview_ready': bool(deck.get('overview_ready')),
            'detail_ready': bool(deck.get('detail_ready')),
            'detail_window': sorted(wanted),
        }
        self.states[number] = {'generation': generation, 'clock': clock, 'position': position,
                               'overview': overview, 'overview_records': records}

    def status(self):
        decks = {}
        for number, coverage in self.coverage.items():
            expected = {(number, 9, timestamp) for timestamp in coverage['detail_window']}
            decks[number] = {**coverage,
                             'detail_tiles_sent': len(expected & self.acked.keys()),
                             'detail_tiles_pending': sum(self.queue.contains(k) for k in expected),
                             'overview_chunks_sent': sum((number, 7, i) in self.acked for i in range(8)),
                             'metadata_sent': (number, 1, 0) in self.acked,
                             'numeric_sent': (number, 4, 0) in self.acked}
        sent = {kind: 0 for kind in (10, 33, 34, 36)}
        for kind, index, packet in self.aux_records:
            if self.acked.get(('aux', kind, index)) == packet:
                sent[kind] += 1
        return {'sent': self.queue.sent, 'bytes': self.queue.bytes_sent,
                'dropped': self.queue.dropped, 'stale': self.stale, 'decks': decks,
                'transport': {'target_hz': 1 / self.telemetry.interval,
                              'ticks': self.telemetry.ticks,
                              'discontinuities': self.telemetry.discontinuities,
                              'prediction_limit_ms': 50},
                'auxiliary': {**self.aux_status, 'browser_view_test': self.browser_view,
                              'effects_sent': bool(sent[10]), 'heading_sent': bool(sent[34]),
                              'folder_rows_sent': sent[33], 'song_rows_sent': sent[36]}}

    def update_auxiliary(self, state, now, force=False):
        if force or self.auxiliary is None or now >= self.next_auxiliary:
            self.next_auxiliary = now + 0.2
            unit = 1 if self.side == 'left' else 2
            effect = next((e for e in state.get('effects', []) if e['unit'] == unit), {})
            browser = state.get('browser', {})
            value = (effect, browser)
            if value != self.auxiliary:
                self.auxiliary = copy.deepcopy(value)
                records = [(10, 0, protocol.effects(self.side, effect.get('slots', []))),
                           (34, 0, protocol.browser_heading(browser.get('heading', '')))]
                folders, tracks = browser.get('folders', []), browser.get('tracks', [])
                for i in range(8):
                    name = folders[i] if i < len(folders) else ''
                    if name and i == browser.get('selected_folder'):
                        name = '> ' + name
                    records.append((33, i, protocol.folder_row(i, name)))
                for i in range(7):
                    track = dict(tracks[i]) if i < len(tracks) else None
                    if track is not None and i == browser.get('selected_row'):
                        track['title'] = '> ' + track['title']
                    records.append((36, i, protocol.song_row(i, track)))
                self.aux_records = [(kind, index, protocol.encode(self.side, kind, raw))
                                    for kind, index, raw in records]
                self.aux_status = {'effects_available': bool(effect),
                                   'browser_available': bool(browser.get('available')),
                                   'folder_count': len(folders), 'track_count': len(tracks),
                                   'selected_row': browser.get('selected_row', -1),
                                   'first_row': browser.get('first_row', 0)}
        # Retry dropped/expired records on every snapshot without rerasterizing
        # or repacking unchanged text. ACK means host write completion only.
        for kind, index, packet in self.aux_records:
            self.record('aux', kind, index, None, now, priority=2, packet=packet)

    def update(self, state, now):
        if state['session'] == self.session and self.last_clock is not None and state['clock_ms'] <= self.last_clock:
            return False
        if state['session'] != self.session or self.stale:
            for number in self.numbers:
                self.invalidate(number)
            self.states.clear()
            self.telemetry.clear()
            self.invalidate('aux')
            self.auxiliary = None
        self.session = state['session']
        self.last_clock = state['clock_ms']
        self.last_received = now
        self.stale = False
        self.update_auxiliary(state, now)
        decks = {d['deck']: d for d in state['decks']}
        for number in self.numbers:
            self.update_deck(decks.get(number, {'deck': number, 'loaded': False, 'generation': -1}),
                             state['clock_ms'], now)
        return True

    def tick(self, now):
        if now-self.last_received > 1 and not self.stale:
            self.stale = True
            self.telemetry.clear()
            self.next_stale_refresh = now
            for number in self.numbers:
                self.invalidate(number)
            self.invalidate('aux')
            self.auxiliary = None
        if self.stale and now >= self.next_stale_refresh:
            # Retry expired warnings and finish the bounded blank-tile window
            # even when the producer remains absent. ACKs keep this change-only.
            self.next_stale_refresh = now + 0.05
            self.update_auxiliary({}, now, force=True)
            for number in self.numbers:
                self.update_deck({'deck': number, 'loaded': True, 'generation': -2,
                                  'title': 'BiteDJ data unavailable', 'playing': False},
                                 (self.last_clock or 0)+1000, now)
        for deck, clock, speed in self.telemetry.due(now):
            self.record(deck['deck'], 5, 0, protocol.playhead(deck, clock, speed), now, ttl=0.1)
        self.queue.pump(now)


def run(args):
    path = Path(args.socket)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    lock = (path.parent / 'service.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return  # launcher may be called repeatedly
    path.unlink(missing_ok=True)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(str(path))
    os.chmod(path, 0o600)
    sock.setblocking(False)
    running = True
    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    screens, names, errors = {}, {}, {}
    received = invalid = 0
    next_discovery = next_status = 0
    latest = None
    latest_time = 0
    try:
        while running:
            now = time.monotonic()
            if now >= next_discovery:
                ports = discover()
                for side in ('left', 'right'):
                    if side in screens and names.get(side) != ports[side]:
                        screens.pop(side).queue.close()
                    if side not in screens and ports[side]:
                        try:
                            screens[side] = Screen(side, AlsaOutput(ports[side]), now, args.mode,
                                                   args.browser_view, args.transport_hz)
                            names[side] = ports[side]
                            errors.pop(side, None)
                            if latest is not None and now-latest_time < 1:
                                screens[side].update(latest, now)
                        except OSError as error:
                            errors[side] = str(error)
                next_discovery = now+2
            newest = None
            for _ in range(32):
                try:
                    blob, _, flags, _ = sock.recvmsg(60000)
                except BlockingIOError:
                    break
                try:
                    if flags & socket.MSG_TRUNC:
                        raise ValueError('Oversize snapshot')
                    state = validate(json.loads(blob))
                    received += 1
                    # Ignore delayed snapshots within one process session.
                    comparison = newest if newest is not None else latest
                    if comparison is None or state['session'] != comparison['session'] or state['clock_ms'] > comparison['clock_ms']:
                        newest = state
                except (ValueError, TypeError, KeyError, OverflowError):
                    invalid += 1
            if newest is not None:
                latest, latest_time = newest, now
            for side, screen in list(screens.items()):
                try:
                    if newest is not None:
                        screen.update(newest, now)
                    screen.tick(now)
                except (OSError, TimeoutError) as error:
                    errors[side] = str(error)
                    screen.queue.close()
                    del screens[side]
            if now >= next_status:
                status = {'version': __version__, 'mode': args.mode, 'browser_view': args.browser_view,
                          'received': received,
                          'invalid': invalid, 'native_recent': now-latest_time < 1,
                          'hardware_verified': False, 'errors': errors,
                          'screens': {s: {'port': names[s], **v.status()} for s, v in screens.items()}}
                tmp = path.parent / 'status.json.tmp'
                tmp.write_text(json.dumps(status, indent=2)+'\n')
                tmp.replace(path.parent / 'status.json')
                next_status = now+5
            deadline = min((s.telemetry.next_tick for s in screens.values()), default=now+0.01)
            time.sleep(max(0.001, min(0.01, deadline-time.monotonic())))
    finally:
        for screen in screens.values():
            screen.queue.close()
        sock.close()
        path.unlink(missing_ok=True)
        lock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', default=SOCKET_PATH)
    parser.add_argument('--mode', choices=('info', 'overview', 'full'), default='full')
    parser.add_argument('--transport-hz', type=int, choices=range(20, 61), default=60,
                        help='Display-only command-05 cadence; native waveform snapshots stay at 20 Hz')
    parser.add_argument('--browser-view', choices=('preserve', 'performance', 'left', 'right', 'both'),
                        default='preserve', help='Opt-in captured browser visibility experiment; not D. VIEW mapping')
    parser.add_argument('--list', action='store_true', help='Identify ports without opening them')
    args = parser.parse_args()
    if args.list:
        print(json.dumps(discover(), indent=2))
    else:
        run(args)


if __name__ == '__main__':
    main()
