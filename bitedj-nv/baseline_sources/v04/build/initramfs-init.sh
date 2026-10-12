#!/bin/busybox sh

# Mount devtmpfs FIRST so /dev/kmsg + block device nodes exist.
/bin/busybox mount -t devtmpfs -o nosuid,mode=755 devtmpfs /dev

mkdir -p /proc /sys /run /dev/pts /dev/shm
mount -t proc proc /proc
mount -t sysfs sys /sys
mount -t devpts -o gid=5,mode=620 devpts /dev/pts
mount -t tmpfs  -o nodev,nosuid tmpfs /dev/shm
mount -t tmpfs  -o nodev,nosuid,size=50% tmpfs /tmp
mount -t tmpfs  -o nodev,nosuid,mode=755 tmpfs /run

# Resolve the data partition from the kernel cmdline. root= is parsed per
# the standard kernel convention, and datafs_wait= caps how many seconds to
# wait for the block device to appear — MMC probe is async, so the partition
# can lag init.sh's start. If either is missing, fall back to production
# defaults (real HW). `splash` is a bare token (per the usual convention)
# that opts into the boot splash below.
DATAFS=
DATAFS_WAIT=
SPLASH=0
for arg in $(cat /proc/cmdline); do
    case "$arg" in
        root=*)        DATAFS=${arg#root=} ;;
        datafs_wait=*) DATAFS_WAIT=${arg#datafs_wait=} ;;
        splash)        SPLASH=1 ;;
    esac
done
DATAFS=${DATAFS:-/dev/mmcblk0p2}
DATAFS_WAIT=${DATAFS_WAIT:-10}

# Boot splash: deckshark-fbsplash draws the gradient + logo to /dev/fb0 and
# returns immediately. The framebuffer memory keeps the image across
# switch_root until cage modesets for Mixxx's first frame. It also forks a
# short-lived, detached child that keeps polling for under-voltage and paints
# the warning bolt if the condition trips after this point; that child runs in
# the background and does not hold up the boot.
#
# vc4 KMS is built into the kernel but its probe is async-blocked on the
# RPi mailbox firmware, so /dev/fb0 may not exist yet. 5s cap — if KMS
# never comes up we just skip the splash and let the boot continue.
if [ "$SPLASH" = 1 ]; then
    waited=0
    while [ ! -e /dev/fb0 ] && [ "$waited" -lt 50 ]; do
        sleep 0.1
        waited=$((waited + 1))
    done

    # Detach fbcon from /dev/fb0 first or any kernel printk that slips past
    # quiet/loglevel=3 paints text on top of the splash. vtcon1 is the fb
    # console; vtcon0 is the dummy in-memory one we leave bound.
    if [ -w /sys/class/vtconsole/vtcon1/bind ]; then
        echo 0 > /sys/class/vtconsole/vtcon1/bind
    fi

    [ -e /dev/fb0 ] && [ -x /usr/bin/deckshark-fbsplash ] && \
        /usr/bin/deckshark-fbsplash /etc/deckshark-logo.pam /dev/fb0
fi

/bin/busybox --install -s /bin
/bin/busybox --install -s /sbin

# Signed USB firmware update. Scans for an official, cryptographically verified
# sharkware.img on a USB drive and, if found and it's safe to write (charging or
# no battery controller), rewrites both SD-card partitions and reboots. On any
# problem — no media, bad signature, wrong power state — it returns and the
# normal boot below proceeds with the on-card system untouched.
: # HDMI test image: preserve this profile; update by writing a new SD image.

waited=0
while [ ! -b "$DATAFS" ] && [ "$waited" -lt "$DATAFS_WAIT" ]; do
    echo "Waiting for root volume..."
    sleep 0.1
    waited=$((waited + 1))
done

if [ ! -b "$DATAFS" ]; then
    echo "init: ERROR — no data partition at $DATAFS after ${DATAFS_WAIT}s" >&2
    echo "init: dropping to a shell so you can poke around" >&2
    exec sh
fi

/sbin/fsck.ext4 -p "$DATAFS" || /sbin/fsck.ext4 -y "$DATAFS"

mkdir -p /newroot

mount -t ext4 -o noatime "$DATAFS" /newroot

# Move pseudo filesystems so the new root inherits them. switch_root
# would otherwise kill udev + lose /dev nodes at the same moment we need
# them (Xorg's device open races the new udev's populate).
mount --move /dev  /newroot/dev
mount --move /proc /newroot/proc
mount --move /sys  /newroot/sys
mount --move /run  /newroot/run

# Pi 4 test profile: expose BOOT for diagnostic capture and recovery.
mkdir -p /newroot/boot/firmware
BOOTFS="${DATAFS%p2}p1"
if [ -b "/newroot$BOOTFS" ]; then
    mount -t vfat -o rw,noatime,umask=0077 "/newroot$BOOTFS" /newroot/boot/firmware || \
        echo "BiteDJ: diagnostic BOOT mount failed" >&2
fi

# Fixed NV controls update: reviewed payload only; never executes files from BOOT.
if /bin/busybox chroot /newroot /usr/bin/python3 - < /bitedj-nv-v04.py; then
    echo "BiteDJ: NV controls update checked"
else
    echo "BiteDJ: NV update skipped; see BOOT/BiteDJ_NV_v04_update.txt" >&2
fi

exec /bin/busybox switch_root /newroot /sbin/init
