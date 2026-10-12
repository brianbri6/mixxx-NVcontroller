# SD music disappearance and v0.5.5 repair

## Evidence from preserved files

- The inspected v0.5, v0.5.1, v0.5.2, v0.5.3 and v0.5.4 initramfs `/init` scripts mount the OS and BOOT only. None mounts a MUSIC partition. They derive from the preserved v0.3 base, not a merge of a user's modified initramfs. The exact last working SD image has not been supplied.
- `work/rootfs/usr/sbin/init` creates a tmpfs on `/media` before udev coldplug. A MUSIC mount made under `/media` earlier in the boot can be covered by it.
- `work/rootfs/etc/udev/rules.d/99-usb-automount.rules` covers USB partitions, not internal MMC partitions. The supplied fstab does not configure the music mount.
- The pinned BiteDJ `src/library/browse/browsefeature.cpp` reads subdirectories under `/media`, `/media/$USER` and `/run/media/$USER` for Removable Devices. It does not mount the SD partition. Its native browser exporter reads existing models and does not change library paths.
- Earlier discussion proposed p1 BOOT, p2 ext4 OS and p3 exFAT MUSIC, but several mount paths were discussed. That is context, not proof of the card's present layout.

Missing or hidden mounting is the leading explanation. No current F12 or block-device report confirms the cause on the user's card. Existing music files are not shown to be deleted, and library/playlist path migration is not justified by the evidence.

## Implemented behavior

`runtime/launch.sh` calls `runtime/sd_music.py` before either the native NV app or the original app (`off` mode). This is after PID1's `/media` setup. It serializes with a lock, probes only extra partitions on the root filesystem's MMC card, checks device identity and requires a unique MUSIC label. Existing whole-filesystem mounts are retained. Only exFAT/FAT/ext4 can be newly mounted, at `/media/MUSIC`, with `rw,nosuid,nodev,noexec,noatime`.

The helper refuses an early mount before the tmpfs exists, a nonempty/symlink/occupied destination, an ambiguous label or changed device/mount state. It uses a 12-second command budget, 2-second filesystem probes and an 8-second mount limit. An unsuccessful mount does not prevent the app launching; only an empty helper-created target is removed on failure. No user mount is unmounted or remounted.

BOOT/BiteDJ_SD_music.txt is validated as the single word auto or off. Absent means auto. This file is not installed or overwritten by the updater. No partitioning, formatting, fsck, music-file edits or library database edits occur. A normal read-write mount can update filesystem metadata.

F12 includes `sd-music-status.json`, `sd-music.log`, `/proc/partitions`, `/proc/filesystems`, `/proc/self/mountinfo`, the option file and the pre-existing mounts/config/log evidence.

## Verification and limits

Fourteen SD tests use fake block/probe/mount records and execute the real launcher with fixture paths and failing helper processes. No physical filesystem is mounted during tests. They cover startup ordering, all display modes, idempotence, timeouts, unsupported/missing/ambiguous candidates, root/device identity, mount races, collisions and existing readonly/custom mounts.

Hardware test: boot v0.5.5, expand Computer → Removable Devices → MUSIC, browse and load tracks, then export F12. Verify the path in status and playback/USB/NV behavior. If the card uses a different label/root layout or already has a custom mount, inspect diagnostics before any further change. Existing playlists tied to a different historical path may need a separate path-preserving solution. Do not guess the old mount path or automatically rewrite the library.

Build/test commands and complete continuation state are in CODEX_PROGRESS.md and NEXT_TASK.md. Existing v0.5.4 and older archives remain unchanged.
