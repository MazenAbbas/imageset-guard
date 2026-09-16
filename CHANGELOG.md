# Changelog

## 0.1.0rc1 - 2026-09-16

First public release candidate.

### Included

- Local, read-only validation for image-classification datasets.
- Dataset split and class-structure checks.
- JPEG, PNG, and WebP verification with full pixel decoding.
- Pixel-limit and decompression-bomb protections.
- File-extension and detected-format consistency checks.
- Static-image enforcement.
- EXIF and GPS metadata-presence reporting without exposing metadata values.
- Streaming SHA-256 exact-duplicate detection.
- Detection of repeated files within a class, conflicting labels across classes, and leakage across train, validation, and test splits.
- Deterministic terminal and JSON reports.
- Stable exit codes for automation.
- Windows, Linux, and macOS CI across Python 3.11 through 3.14.

### Important limitations

- Exact-byte duplicate detection only; no perceptual similarity detection.
- No licensing, consent, bias, malware, NSFW, or semantic-label validation.
- This release candidate should be evaluated before the final v0.1.0 release.
