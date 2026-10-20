#!/bin/sh
# Preserve the appliance wrapper's arguments, settings and CPU affinity.
set -eu
SLOT=/usr/local/lib/bitedj-nv-v058
ORIGINAL_BIN=$1
shift
MODE=full
MODE_FILE=/boot/firmware/BiteDJ_NV_display_mode.txt
if [ -f "$MODE_FILE" ]; then
    MODE=$(tr -d '\r\n ' < "$MODE_FILE")
fi
mkdir -p /tmp/bitedj-nv
chmod 700 /tmp/bitedj-nv
# PID1 has now mounted /media as tmpfs. Mount SD music before library discovery,
# including when the NV display bridge is off. Failure must not stop the app.
/usr/bin/python3 "$SLOT/sd_music.py" > /tmp/bitedj-nv/sd-music.log 2>&1 || true
# Before the app opens MIDI: reserve only the two display ports and load numeric tuning.
# A malformed settings file must not prevent audio/HDMI startup.
/usr/bin/python3 "$SLOT/nv_settings.py" || true
case "$MODE" in
    off) exec "$ORIGINAL_BIN" "$@" ;;
    info|overview|full) ;;
    *) MODE=full ;;
esac
export BITEDJ_NV_SOCKET=/tmp/bitedj-nv/state.sock
export BITEDJ_NV_DETAIL=0
[ "$MODE" != full ] || export BITEDJ_NV_DETAIL=1
export PYTHONPATH="$SLOT"
BROWSER_VIEW=preserve
if [ -f /boot/firmware/BiteDJ_NV_browser_view.txt ]; then
    BROWSER_VIEW=$(tr -d '\r\n ' < /boot/firmware/BiteDJ_NV_browser_view.txt)
fi
case "$BROWSER_VIEW" in
    preserve|performance|left|right|both) ;;
    *) BROWSER_VIEW=preserve ;;
esac
# The renderer is a normal-priority process on the inherited housekeeping CPUs.
# Its failure cannot block the audio engine or the GUI startup.
(
    ulimit -f 1024
    exec /usr/bin/python3 -m nvdisplay.service --mode "$MODE" --browser-view "$BROWSER_VIEW"
) > /tmp/bitedj-nv/service.log 2>&1 &
exec "$SLOT/bitedj" "$@"
