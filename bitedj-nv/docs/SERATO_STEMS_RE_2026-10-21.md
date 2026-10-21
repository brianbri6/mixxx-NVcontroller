# Serato DJ iOS 5.0.0 Stems — reverse-engineering continuation (2026-10-21)

**Project:** Original Numark NV, Pi 4 Mixxx/BiteDJ, Android NVDJ. Documentation only; no app code changed.

## Verified directly from supplied iOS IPA
- `SeratoDJ.z01` + `SeratoDJ.zip` contain `SeratoDJ.ipa`, bundle `com.serato.dj`, version `5.0.0` (build `5.0.0.1168`).
- Main Mach-O FairPlay `cryptid=1` covers bytes 16,384 through 49,037,311 (49,020,928 encrypted bytes). A separate 7,147,712-byte clear tail has symbol/type metadata, but not the protected separation code.
- Clear type names: **`machine_learning::CoreMLModelRunner`, `ModelRunnerAudioSourceSeparator`, `ModelRunnerBeatDetector`, `Stemifier`, `StemData`, `StemsEntry`, `StemAudioCacheProviders`, `DeckCacheStrategyController`, `currentStemAudioCacheURIs`**, `StemFxBehavior`, `AnalyzeStemsOnTrackLoad`. CoreML imports include `MLModel`, `MLModelAsset`, `MLModelConfiguration`, `MLPredictionOptions`.
- These names strongly establish a source-separation implementation plus CoreML runner abstraction. The actual model topology, weights, compute-unit selection (CPU/GPU/Neural Engine), cache format on iOS, and method call order **remain unknown**.
- A **524,247,312-byte** `bundle2.bin` was scanned: SHA256 `8ad97f0a84404bfcac3829facb07f3214226482254f090dc80a5e7c15c79fcd4`; samples from 0%,25%,50%,75%,95% show ~7.993–7.994 bits/byte Shannon entropy, zlib ratio ~1.0, ~50% randomly interpreted float32 values below magnitude 10. First u64-LE is 1020 (unknown meaning). It is opaque, consistent with compressed/encrypted resources, NOT directly readable float32 model weights. Isolated 4-byte hits like `onnx` and `stft` are statistically expected false positives. **Do not claim it contains a specific model.**
- No clear independently packaged `.mlmodel`, `.mlmodelc`, `.onnx`, `.tflite`, or named Demucs/Spleeter/RoFormer models are listed in the IPA.
- **Result:** No justified model name (Demucs / MDX-Net / RoFormer / proprietary) can be supplied. CoreML use does NOT establish Neural Engine use.

## Observed/published features (outside IPA code)
- Official iOS v5.0 release on **2026-10-20** confirms four musical parts: vocals, bass, drums, melody, with acapella and instrumental controls. Instrumental can be synthesized as a combination of the three non-vocal parts, not a fifth independently stored separated source. See https://serato.com/dj/for-ios/release-notes.
- Serato supports on-demand preparation plus `Analyze Stems` on song load. On desktop prepared stems can persist as `.serato-stems` sidecars next to tracks: https://support.serato.com/hc/en-us/articles/5700969287183-Preparing-tracks-for-use-with-Stems. This doesn't prove the *iOS-specific* cache path.

## NEW: externally verified Serato 3.x desktop sidecar format — not from IPA
Public independent parsers: https://github.com/rdkrl/sidecaramel/blob/main/sidecaramel/stems.py and https://gist.github.com/fsalomon/ff46efc0dfbb0e88afbec396e85cf1a3 . Sidecaramel reports checks against real Serato 3.x samples; **Serato iOS 5.0 sidecars not yet tested**.

```
0..7     ASCII "srtshead"
8..11    u32 big-endian header_length =16
12..13   u16 big-endian version_major
14..15   u16 big-endian version_minor
16..19   u32 big-endian stem_count (commonly 4)
20..23   u32 big-endian total_samples
24..27   u32 big-endian sample_rate
28..     repeated "stem" + u32 big-endian length + u32 big-endian type + XOR 0x26 MP3 stream
         length includes 4-byte type, so MP3 starts at chunk offset +12
         type 0 vocals, 1 bass, 2 drums, 3 harmony/melody
```

- These are **four MP3-compressed** streams. XOR 0x26 is a reversible format obfuscation, not machine learning and not FairPlay encryption. Real Serato MP3 streams may carry LAME Xing encoder delay/end padding; correct decoding must honor this for *sample-accurate* mixing. The independent reference tested 576-sample delay and 576 padding in one file; don't hardcode these figures.
- A **standalone Python source inspector** and 3 passing **synthetic** tests were delivered to the originating chat as `Serato_Stems_RE_Toolkit_2026-10-21.zip`. It inspects the Serato sidecar and optionally extracts its four MP3s, no overwrite. No genuine user sidecar was available to test.

## For Android NVDJ: strictly OPTIONAL future module
- Preserve currently working VDJ `.vdjstems` **five AAC streams**; it is a different format and the Serato reader must not replace existing decoder.
- Future Serato import module: detect `srtshead`, build nonblocking per-stem MP3 decoder, maintain sample accuracy via encoder-delay data, and map instrumental=drums+bass+melody at mix time.
- Keep stem **generation**, **prepared compressed cache**, **decode**, and **instantaneous mute/solo** isolated from the real-time audio callback. Do not change existing application without tests.
- To identify Serato's true neural weights, a validated model specification/weights or authorized runtime metadata is required; do not guess from container size or CoreML imports.

## Next test
Obtain a *legitimately generated* small desktop `.serato-stems` file (for a track the user can share), inspect types/codec/sample rate and verify gapless alignment. This will help interoperability but not identify the inference model. Separately, test iOS-generated caches if the stock device exposes them.
