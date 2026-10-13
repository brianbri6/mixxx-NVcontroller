# Exact continuation prompt

Continue the original Numark NV + Deckshark/BiteDJ Pi4 4GB mixed-folder browser fix. Inspect git status/diff/history and CODEX_PROGRESS.md first. Preserve completed work. Maintain progress, commit milestones, publish source to the user's brianbri6/mixxx-NVcontroller GitHub fork, and save durable recovery. Do not spawn subagents, bypass AF_UNIX restrictions, overwrite released ZIPs, or change HDMI waveforms/audio settings.

## Current work

v057 archive built from 4abc4e7; saved as libfile_27671c0941708191917df7cb39e8fc7f version0. Check CODEX_PROGRESS for recovery receipt. SHA-256 ee028b53112635468dbccb4010ce5549cafa4a478398e83bba675e958c60d970 (24,650,131 bytes). v057 adds native/browser_navigation.patch against TeamDeckshark/bitedj commit 78074e05c8bf99ede6fedd755aa68bd222ba343c. SidebarModel identifies real Browse directories as owning tracks even with children; label/enter opens tracks while expansion stays separate. Controller note06 navigation enters tracks normally, Shift+navigation expands/collapses in sidebar, either returns from tracks to folders. Do not claim the unidentified encoder center press is fixed. D.VIEW/artwork/cue overlays remain incomplete.

Workspace repeatedly returns to e9e6687. This run preserved dirty old files in a stash and fast-forwarded recovery bundle f3e0bec, then restored native fix files from GitHub 7c557b60f6ff48ae13a8d395b978b2fc7fa6a8a0. Prefer newer published source/recovery over stale local files. GitHub integration lives under bitedj-nv/; preserve the upstream fork root. Root res/controllers copies should mirror controller sources when published. Do not reset completed work.

v057 slot/journal/version preparation includes pinned v056, 47 passed actual-payload upgrade/rollback/fault cases, and refuses reuse of the old v054 native binary. Source-level checks passed 71 Python +26 JS this run. Check latest progress for build, package and delivery results. Fresh ARM64 build, 127-file ABI audit, QEMU version check and all 47 payload scenarios passed. See newest progress for release save receipt. No physical acceptance here.

## Exact commands

```sh
git status --short
git diff
git log -6 --oneline
# If source absent, restore exact pinned checkout:
git clone --filter=blob:none --no-checkout https://github.com/TeamDeckshark/bitedj.git vendor/bitedj
git -C vendor/bitedj checkout 78074e05c8bf99ede6fedd755aa68bd222ba343c
python3 scripts/apply_native.py
# Only if toolchain missing:
python3 scripts/prepare_toolchain.py > work/toolchain-v057.log 2>&1
# A fresh native build is required for this patch:
NV_BUILD_JOBS=6 sh scripts/build_arm.sh > work/build-arm-v057.log 2>&1
python3 scripts/audit_arm.py
python3 scripts/check_native_version.py
node tests/test_controller.js > work/test-controller-v057.log 2>&1
python3 -m unittest discover -s tests -v > work/test-v057.log 2>&1
python3 scripts/verify_captures.py
sh -n runtime/launch.sh
python3 scripts/build_update.py --native-binary work/build-arm/mixxx > work/test-package-v057.log 2>&1
git diff --check
# Commit tracked source before packaging.
python3 scripts/package_release.py
python3 scripts/checkpoint.py --with-native-build --with-package
```

Restore pinned baseline releases v05 through v056 from INPUTS.json. v056 is libfile_324e0e3b3b58819183a3c1e406638746, SHA cdf27c6c1ab35f4aa01df2bdc4c7ff4794d729d59171d42c83eca225133a25c7. Recovery identity libfile_5ce7b9ccc09c8191b0a53b70932cc2aa; version25 confirmed before final receipt refresh. Resolve fresh guard before replacing. Keep original captures/manual, native evidence/binary and validation logs. Do not restamp old native evidence. Save new release separately.

Hardware checklist: Folder1 with direct songs +Folder2 with different songs; clicking Folder1 label shows only its songs on HDMI/NV; arrow or Shift+navigation exposes Folder2; entering Folder2 shows its songs. Return and repeat, test empty folder, normal track load and existing FX/audio. Keep HDMI waveforms disabled. Collect F12/photos for remaining LCD or center-push failures.
