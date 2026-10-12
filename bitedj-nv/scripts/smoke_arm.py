#!/usr/bin/env python3
"""Emulated ARM app smoke test with the base image libraries and a generated WAV.

This is not a Pi boot, USB LCD test or real-time/audio performance test.
"""
import json
import math
import os
from pathlib import Path
import shutil
import signal
import socket
import struct
import subprocess
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from nvdisplay.service import validate


def main():
    out = ROOT/'work/smoke'
    settings = out/'settings'
    settings.mkdir(parents=True, exist_ok=True)
    (out/'runtime').mkdir(mode=0o700, exist_ok=True)
    cfg = ROOT/'work/rootfs/root/.mixxx/mixxx.cfg'
    shutil.copy2(cfg, settings/'mixxx.cfg')
    track = out/'NV_Test_Tone.wav'
    with wave.open(str(track), 'wb') as w:
        w.setparams((2, 2, 44100, 0, 'NONE', 'not compressed'))
        for second in range(8):
            frames = bytearray()
            for i in range(44100):
                sample = int(16000*math.sin(2*math.pi*(220+second*55)*i/44100))
                frames.extend(struct.pack('<hh', sample, sample))
            w.writeframes(frames)
    sockpath = out/'native.sock'
    sockpath.unlink(missing_ok=True)
    try:
        receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    except PermissionError as error:
        result = {'passed': False, 'blocked': True, 'hardware_tested': False,
                  'reason': 'This execution environment forbids AF_UNIX sockets: ' + str(error)}
        (out/'result.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps(result, indent=2))
        return 2
    receiver.bind(str(sockpath))
    receiver.settimeout(0.25)
    env = dict(os.environ)
    env['LD_LIBRARY_PATH'] = str(ROOT/'work/host-compat')
    qemu = ROOT/'work/hostroot/usr/bin/qemu-aarch64'
    rootfs = ROOT/'work/rootfs'
    args = [str(qemu), '-L', str(rootfs), '-U', 'LD_LIBRARY_PATH',
            '-E', 'QT_QPA_PLATFORM=offscreen',
            '-E', 'QT_PLUGIN_PATH='+str(rootfs/'usr/lib/aarch64-linux-gnu/qt6/plugins'),
            '-E', 'XDG_RUNTIME_DIR='+str(out/'runtime'),
            '-E', 'BITEDJ_NV_SOCKET='+str(sockpath), '-E', 'BITEDJ_NV_DETAIL=1',
            str(ROOT/'work/build-arm/mixxx'), '--settings-path', str(settings),
            '--resource-path', str(rootfs/'usr/share/mixxx'), str(track)]
    result = {'hardware_tested': False, 'emulated': True, 'valid_snapshots': 0,
              'track_loaded': False, 'overview_ready': False, 'detail_ready': False}
    started = time.monotonic()
    with (out/'app.log').open('w') as log:
        process = subprocess.Popen(args, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            while time.monotonic()-started < 45 and process.poll() is None:
                try:
                    data = receiver.recv(60000)
                except socket.timeout:
                    continue
                snapshot = validate(json.loads(data))
                result['valid_snapshots'] += 1
                for deck in snapshot['decks']:
                    if deck['loaded']:
                        result.update(track_loaded=True, title=deck.get('title'),
                                      duration_ms=deck.get('duration_ms'))
                        result['overview_ready'] |= bool(deck.get('overview_ready'))
                        result['detail_ready'] |= bool(deck.get('detail_ready'))
                        (out/'loaded-snapshot.json').write_text(json.dumps(snapshot, indent=2)+'\n')
                if all(result[k] for k in ('track_loaded', 'overview_ready', 'detail_ready')):
                    break
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            receiver.close()
            sockpath.unlink(missing_ok=True)
    result['process_exit'] = process.returncode
    result['elapsed_seconds'] = round(time.monotonic()-started, 2)
    result['passed'] = all(result[k] for k in ('track_loaded', 'overview_ready', 'detail_ready'))
    (out/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
