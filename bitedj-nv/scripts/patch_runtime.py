#!/usr/bin/env python3
"""Make reviewed appliance launcher/diagnostic patches; don't modify the base."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'work/rootfs'
OUT = ROOT/'work/payload'


def make():
    launcher = BASE/'usr/bin/start-mixxx'
    text = launcher.read_text()
    old = '    exec $MIXXX_BIN $MIXXX_ARGS\n'
    new = '''    # NV display bridge v0.5.7; launch.sh supports BOOT mode "off".
    exec /usr/local/lib/bitedj-nv-v057/launch.sh "$MIXXX_BIN" $MIXXX_ARGS
'''
    if text.count(old) != 1:
        raise RuntimeError('Unexpected Pi4 launcher: review before patching')
    target = OUT/'usr/bin/start-mixxx'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text.replace(old, new))
    target.chmod(0o755)
    diag = BASE/'usr/local/share/bitedj-diag/diag.py'
    text = diag.read_text()
    old = "'wm.log':RAM/'wm.log',"
    new = "'nv-status.json':'/tmp/bitedj-nv/status.json', 'nv-service.log':'/tmp/bitedj-nv/service.log', 'nv-settings-status.json':'/tmp/bitedj-nv/settings-status.json', 'sd-music-status.json':'/tmp/bitedj-nv/sd-music-status.json', 'sd-music.log':'/tmp/bitedj-nv/sd-music.log', 'nv-update.txt':BOOT/'BiteDJ_NV_v057_update.txt', 'nv-v056-update.txt':BOOT/'BiteDJ_NV_v056_update.txt', 'nv-v055-update.txt':BOOT/'BiteDJ_NV_v055_update.txt', 'nv-v054-update.txt':BOOT/'BiteDJ_NV_v054_update.txt', 'nv-v053-update.txt':BOOT/'BiteDJ_NV_v053_update.txt', 'nv-v052-update.txt':BOOT/'BiteDJ_NV_v052_update.txt', 'nv-v051-update.txt':BOOT/'BiteDJ_NV_v051_update.txt', 'nv-v05-update.txt':BOOT/'BiteDJ_NV_v05_update.txt', " + old
    if text.count(old) != 1:
        raise RuntimeError('Unexpected diagnostics script: review before patching')
    text = text.replace(old, new)
    old = "'/proc/version','/proc/mounts',"
    new = old + "'/proc/partitions','/proc/filesystems','/proc/self/mountinfo','/boot/firmware/BiteDJ_SD_music.txt',"
    if text.count(old) != 1:
        raise RuntimeError('Unexpected diagnostics snapshot: review before patching')
    target = OUT/'usr/local/share/bitedj-diag/diag.py'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text.replace(old, new))
    target.chmod(0o755)


if __name__ == '__main__':
    make()
