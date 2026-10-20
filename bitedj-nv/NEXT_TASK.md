# Exact continuation prompt

AI-generated continuation notes.

Continue the original Numark NV + BiteDJ Pi4 4GB project from the newest recovery checkpoint and GitHub working branch `nv-learned-inputs-led-discovery-20261019`. Inspect `git status --short`, `git diff`, recent history and `CODEX_PROGRESS.md` before editing. Preserve v057 native mixed-folder activation, working SD MUSIC mounts, audio settings, HDMI waveforms disabled, scratch/VU/FX/browser fixes. Maintain progress and milestone commits. Do not spawn subagents, bypass AF_UNIX restrictions, overwrite released ZIPs, or copy proprietary IPA/APK/music into source.

## Current work

v058 implements the handoff `docs/NV_SERATO_IOS_HANDOFF_2026-10-20.md` from main fe7285ee6 and diagnostic branch6ef68728. See `docs/NV_INTEGRATION_V058.md`. Python command05 target60Hz uses bounded fresh-snapshot prediction while native waveform sampling remains20Hz. Whole-record token admission prevents a tile from blocking new transport for lack of tokens; real partial SysEx stays atomic. No native change/rebuild. Inputs:142 exact learned messages,30 release bindings; Sel07 +Slip04, independent channel/masterFXA/B, preserved explicit unroute, held LED cleanup, CueBlend7-bit, Beatkeeper BOOT options, pad codes4/16.

Known gaps: D.VIEW outgoing3-view commands, artwork/beat/cue/loop overlays, physical masterVU/red confirmation, touch/filter-roll/Beat-divisor/switch audio behavior beyond recorded labels, sustained Pi audio and HDMI-disconnected boot. Handoff's Serato architecture is static evidence, not recovered DSP. The separate Android project is not modified in this workspace.

The prior interrupted v058 changes were pruned before a checkpoint; this run restored recoveryv26/source36724e6 and reconstructed the delivered subset explicitly. Look at the latest progress receipts for packaged release, recovery version and GitHub commit. Do not assume old recovery25/26 guards remain current when saving again. Preserve all source, full learned metadata and four captures.

## Exact validation/package commands

Run from the project root (GitHub checkout uses `bitedj-nv/`).

```sh
git status --short
git diff
git log -6 --oneline
node tests/test_controller.js > work/test-controller-v058.log 2>&1
python3 -m unittest discover -s tests -v > work/test-v058.log 2>&1
python3 scripts/verify_captures.py
python3 scripts/analyze_handoff.py > work/test-handoff-v058.log
sh -n runtime/launch.sh
git diff --check
PYTHONPATH=scripts python3 -c 'from native_build_evidence import verify; print(verify("work/build-arm/mixxx")["native_sha256"])'
python3 scripts/build_update.py --native-binary work/build-arm/mixxx > work/test-package-v058.log 2>&1
# Commit tracked source/docs before packaging; never overwrite a delivered ZIP.
python3 scripts/package_release.py
python3 scripts/checkpoint.py --with-native-build --with-package --github-source-ref PUBLISHED_COMMIT
```

Expected current suite:78Python +33JS,4458 captured LCD messages,112 control OUT addresses,142 learned input bindings. Updater58 paths include all v057 upgrade histories and write-error/power-loss recovery. Latest progress states whether package validation/delivery completed. Existing native unstripped SHA9083092b6908ecb54ef8fda2f89e8bab9c92b9352974c1996021e93d74d9f685 and stripped SHA2d176dfd90d2031bb1f14fc9ca653ecf4816a2ce20bab4dda1697d38a3e9fa23 must remain matched to saved evidence.

## Restore after cleanup

Restore newest `BiteDJ_NV_Recovery_Checkpoint.zip` (identity libfile_5ce7b9ccc09c8191b0a53b70932cc2aa; resolve current version). New checkpoints use GITHUB_SOURCE.json: clone the exact published repository commit, use its bitedj-nv/ subdirectory as project root, then restore source/project_sources capture inputs and build-artifacts/work with fresh writes, not historical-mtime copy2. Older checkpoints contain repository.bundle/source instead. Git-backed source is preserved on GitHub; build outputs and original captures stay in the checkpoint. Preserve newer surviving edits first. Baseline release ZIPs v05 throughv057 and original v03 are pinned in INPUTS.json. Latest GitHub main may have additional handoff documents; compare before publishing.

```sh
git clone --filter=blob:none --no-checkout https://github.com/TeamDeckshark/bitedj.git vendor/bitedj
git -C vendor/bitedj checkout 78074e05c8bf99ede6fedd755aa68bd222ba343c
python3 scripts/apply_native.py
python3 scripts/extract_image.py baseline/BiteDJ_Pi4_4GB_HDMI_NV_Test_v0_3.zip --output work/base
mkdir -p work/rootfs
debugfs -R 'rdump / work/rootfs' work/base/root.img
```

v058 builder copies the exact stripped executable from hash-pinned v057 after matching recovered native source/build evidence. No toolchain is needed. Native edits require a new build, ABI/version evidence and a future version; do not relabel old evidence. Preserve original GitHub fork root; sync the Pi project under bitedj-nv plus two res/controllers mapping copies. Keep this diagnostic working branch separate from main until hardware checks recorded.

Next hardware evidence: video of NV transport under play/pause/scratch/reverse/seek/loop and heavy browsing, parent/child song navigation using Sel/Shift+Sel, FX independent channel/master routes, Beatkeeper and pad colors, F12 export. Use the supplied reversible update and leave audio/HDMI settings unchanged. No physical hardware result is implied by offline tests.

End AI-generated continuation notes.
