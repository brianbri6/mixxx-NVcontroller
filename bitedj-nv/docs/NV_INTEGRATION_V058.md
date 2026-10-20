# v0.5.8 — diagnostic and Serato/VDJ handoff integration

AI-generated integration record.

Sources: main fe7285ee679afdff677a634ecc96a1112ef0e88f handoff, diagnostic branch 6ef687287692065ab057973f46677a0be12d0ee6, Diagnostic v0.15 mapping catalog, user learned inputs, original NV manual v1.2 and four USB captures pinned in INPUTS.json. No proprietary IPA/APK bytes or music are included in source or releases.

## Findings applied

| Evidence | Implementation | Limit |
|---|---|---|
| Command05: 29 wire bytes, median15.81ms in active capture | Separate Python60Hz display transport scheduler | This is a target; actual USB/CPU latency and screen smoothness need hardware measurement |
| Command09: 2491 wire bytes, median126.5ms | Retain cached tiles and native20Hz peak snapshots; wait for whole-record byte budget before starting a tile | Cannot interrupt a real partial SysEx; backlog can delay updates |
| Position/angle/speed are host display output | Predict at most50ms from fresh measured position slope; paused motion at most16ms; conservative4x speed guard | Does not change jog sensitivity; loops/seeks less than guard threshold may be corrected on next sample |
| Track/session changes and discontinuities | Invalidate obsolete unsent tiles, latest playhead coalescing, zero-speed reset, stale-state warning retained | Source snapshots can have GUI delivery latency; no claim of true60Hz sampling |
| 142 learned inputs /98 addresses,30 missing release bindings | Exact values named and retained in full metadata; XML routes each address | Touch sensors, hardware switches and Beat/divisor controls without implemented semantics remain bounded observations |
| Sel07 /Slip04 | Existing mixed-folder navigation including Shift-expand; press/release debounce | D.VIEW output cycle remains unknown |
| Manual FX A and/orB, channels and/orMain | Independent A/B routes, route LEDs, slot controls respect explicit unroute and wet/dry | No inferred Serato single-FX DSP behavior |
| Beatkeeper OFF0/positions1..11/center6 | Active-left/right tempo comparison, configurable deadband/step | Thresholds are software choices; physical behavior pending |
| CueBlend single7-bit / pad codes4,16 captured | Correct scaling; expanded bounded palette | No arbitrary RGB or named-color claims |
| Shader/stems/type names in encrypted Serato iOS app | Retain provenance and design notes for separate Android work | No decrypted DSP/model/file-format implementation; shader levels do not identify NV VU addresses |

The diagnostic branch's exclusive A/B routing is superseded by this implementation. Its observations remain documented in NV_LED_DISCOVERY_20261019.md. Full user learned metadata is preserved semantically; CRLF was normalized to LF for source. References distinguish controller IN/OUT and separate LCD USB functions.

Native exporter/browser patch and exact v057 executable are unchanged. Hence prior native ABI/version evidence remains valid, while every changed Python/JS payload receives new v058 tests and a separate install/rollback journal. No HDMI, sound routing, buffer or realtime settings are changed.

## Hardware acceptance

1. Preserve current BOOT files, install the v058 update, then check Folder1 direct songs and Folder2 songs separately on HDMI/NV. Press Sel from folders/tracks and Shift+Sel to expand children; Load stays separate.
2. With analyzed tracks, film LCD transport while playing, pausing, slowly scratching, reversing, seeking and looping. Repeat with layers3/4 and rapid browsing. Inspect F12 transport counters, source freshness and output errors; audible performance is the deciding criterion.
3. Test FX A+B simultaneously on each channel and Main, disable both then use slot buttons, confirm no unexpected route reappears. Check reverse/bend LEDs after layer switch, Slip press/release, CueBlend range and Beatkeeper center/left/right/unloaded.
4. Palette4/16 and masterVU red5 remain physical checks; use silent lamp tests. Record D.VIEW input/output with working vendor software to resolve three-view outputs. Do not replay unrelated startup/challenge traffic.

For an A/B comparison on the Pi, stop the launcher-managed display service first so only one owns the MIDI ports, then run `python3 -m nvdisplay.service --mode full --transport-hz 20` or `--transport-hz 60` from the installed runtime directory. Keep the native snapshot producer/socket setting intact. Standard startup uses60Hz; full rollback restores previous cadence. Do not run competing raw MIDI writers.

End AI-generated integration record.
