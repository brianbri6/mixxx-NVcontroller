# Pi4 / original Numark NV — v0.5.8 source package

AI-generated source-package instructions.

This ZIP contains the complete tracked **BiteDJ Pi integration project** with all current changes. It is for Raspberry Pi4 4GB and the original Numark NV. Open this file first; README.md also contains instructions for the separate installable update, which is still pending recovery of its build inputs.

## Included

- Controller JavaScript/XML, full learned-input metadata and settings: scratch/VU, FX routing and adjustment, captured-palette pads, Sel/Shift+Sel browser navigation and diagnostic feedback.
- Native C++ NV exporter, mixed-folder patch and exact upstream application/build scripts.
- Python LCD renderer/protocol/queue and bounded target60Hz transport, while native waveform snapshots remain20Hz.
- SD MUSIC helper, launcher, reversible v058 installer and rollback implementation.
- Tests and fixtures, diagnostic mapping catalog, capture-derived evidence, the Serato/VDJ handoff, licenses, CODEX_PROGRESS.md and NEXT_TASK.md.
- SOURCE_ORIGIN.json identifies the exact source commit and subtree; SOURCE_SHA256SUMS.txt hashes this snapshot. SOURCE_MANIFEST.json is an older historical recovery manifest and is not the current ZIP's checksum list.

The unchanged upstream BiteDJ source is fetched at the pinned commit below. Raw USB captures/manual and baseline release images are separate inputs listed in INPUTS.json. No compiled application, initramfs, SD image, Android app, proprietary APK/IPA, music, dependency cache or credentials are included.

## Test the source

Use Linux with Git, Python3, Node.js and a C++17 compiler. From the extracted project directory:

```sh
mkdir -p work
git clone --filter=blob:none --no-checkout https://github.com/TeamDeckshark/bitedj.git vendor/bitedj
git -C vendor/bitedj checkout 78074e05c8bf99ede6fedd755aa68bd222ba343c
python3 scripts/apply_native.py
python3 -m unittest discover -s tests -v
node tests/test_controller.js
sh -n runtime/launch.sh
```

The restored integration passed78 Python tests and33 controller tests. Native browser tests use the patched source with minimal C++ model doubles; they are not a Qt GUI test. Without vendor/bitedj, native-source tests explicitly skip. Full original-capture validation needs all four pinned PCAPs under project_sources/:

```sh
python3 scripts/verify_captures.py
python3 scripts/analyze_handoff.py
```

Expected full capture coverage is4458 LCD records. Only3531 records from the two attached captures were available for the latest rerun; all four passed in the earlier integration milestone.

## Build an installable update

This source package does not need the missing native binary to be created. Building the installable update does: restore the exact v057 native executable/build evidence, pinned v03 image and v05 throughv057 baseline releases as described in NEXT_TASK.md. Recovery downloads were blocked with HTTP403 in the previous run. No new installable v058 image is claimed by this source ZIP.

For scripts that require Git history, either use the published GitHub checkout/subdirectory identified by SOURCE_ORIGIN.json, or initialize the extracted project as a local Git repository and commit its source first. Keep the published commit identity in SOURCE_ORIGIN.json as provenance.

With restored inputs, the exact update commands are:

```sh
PYTHONPATH=scripts python3 -c 'from native_build_evidence import verify; print(verify("work/build-arm/mixxx")["native_sha256"])'
python3 scripts/extract_image.py baseline/BiteDJ_Pi4_4GB_HDMI_NV_Test_v0_3.zip --output work/base
mkdir -p work/rootfs
debugfs -R 'rdump / work/rootfs' work/base/root.img
python3 scripts/build_update.py --native-binary work/build-arm/mixxx > work/test-package-v058.log 2>&1
python3 scripts/package_release.py
```

The builder retains the source-verified v057 native binary and validates58 install/upgrade/rollback/fault scenarios. If native sources are deliberately changed later, generate a new native build and evidence using scripts/prepare_toolchain.py then sh scripts/build_arm.sh; this requires the original runtime and baseline dependency archive. Do not restamp an older binary to bypass the provenance gate.

To reproduce this source ZIP from a clean Git checkout:

```sh
python3 scripts/package_source.py --output dist/BiteDJ_Pi4_NV_v0_5_8_Source_2026-10-20.zip
```

The packager refuses to overwrite an existing ZIP and verifies every member after creation. Source from bitedj-nv/ in the full GitHub fork is packaged with that subdirectory as its root, excluding unrelated fork files.

## Preserved behavior and remaining work

The parent-folder/direct-song fix, SD MUSIC support, scratch tuning, VU clearing, FX/pad/browser controls and current audio/HDMI settings are preserved. Keep HDMI waveforms disabled as in the smooth Pi4 setup. No Android changes were made.

Outgoing D.VIEW three-view selection, artwork/beat/cue/loop graphics, physical masterVU/red confirmation and sustained audio/headless acceptance remain open. Learned D.VIEW input observations are included; no unknown output commands are guessed. Serato architecture findings do not contain decrypted DSP/stems algorithms. See docs/NV_INTEGRATION_V058.md for the hardware checklist.

End AI-generated source-package instructions.
