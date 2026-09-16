# Changelog

## 0.2.0rc1 - 2026-09-16

Second release candidate. Adds a deterministic dataset profile, an
extensible opt-in policy, explicit layout selection, and CLI usability
improvements, while keeping every v0.1 contract unchanged.

### Added

- **Dataset profile**: every scan now reports deterministic, bounded-
  memory facts -- file counts by split/class, format/color-mode counts,
  width/height/aspect-ratio boundaries (exact min/max, not percentiles),
  empty classes, and a class-balance ratio. Included in both the terminal
  summary and a new additive `"profile"` JSON key. Facts are reported
  regardless of policy; a fact becomes a finding only when a policy limit
  is configured.
- **Policy v2**: `min_images_per_class`, `max_class_imbalance_ratio`,
  `allowed_formats`, `allowed_modes`, `min_width`/`max_width`,
  `min_height`/`max_height`, `min_aspect_ratio`/`max_aspect_ratio`,
  `exif_policy`, `gps_policy`, and an explicit `schema_version` (currently
  `1`). Every field is optional and defaults to v0.1's exact behavior.
  New `imageset-guard policy-check FILE` command validates a policy file
  without scanning any dataset.
- **Explicit layout selection**: `--layout split-class` (default,
  unchanged from v0.1) or `--layout class-only` for datasets with no split
  directories at all (the layout torchvision's `ImageFolder` and Hugging
  Face's single-directory `imagefolder` both use -- see
  `docs/design-decisions.md`). No automatic detection between the two.
- **CLI usability**: `--quiet` (suppresses the terminal summary only,
  never a fatal error or the exit code), `--progress` (periodic
  `inspected N/M` lines to stderr only, never stdout or the JSON report),
  a `doctor` command (environment diagnostics; never reads a dataset), an
  `example` command (writes a tiny local synthetic dataset; no downloaded
  or copyrighted assets), and clean Ctrl+C handling (new additive exit
  code `130`; never publishes a partial report as complete).
- New `POLICYxxx` finding codes (`POLICY001`-`POLICY009`) under a new
  `Category.POLICY`. Every existing `SPLIT`/`IMG`/`PRIV`/`DUP` code keeps
  its original meaning and severity unchanged; a policy violation is
  always reported through a new code, never by changing an old one.
- New additive JSON report keys: `report_schema_version` (starts at `1`)
  and `profile`. Every key/shape v0.1's report defined is unchanged --
  proven by golden compatibility tests in `tests/test_v01_compatibility.py`.
- `docs/guides.md`: tested command sequences for five workflows (student,
  data scientist, ML engineer, data engineer/CI, instructor).
- `benchmarks/`: a reusable, deterministic benchmark harness (generator +
  runner), committed without any generated dataset or machine-specific
  result file.

### Compatibility

- Backward compatible: a v0.1-style policy file (just `max_pixels`, no
  `schema_version`) loads and behaves identically. A v0.1-era JSON
  consumer reading only `status`/`summary`/`findings`/`scan_errors` sees
  no change in those fields' meaning; `report_schema_version` and
  `profile` are new, additive keys only.
- `scan_dataset()`'s Python return type changed from a bare `ScanResult`
  to `(ScanResult, DatasetProfile)`; this is an internal API, not part of
  the CLI/JSON/exit-code contract.

### Measured (one Windows machine, repeated synthetic workload)

10,000-file synthetic workload, 3 repetitions: median wall time 59.00 s
(range 58.74-61.62), median throughput 169.5 files/s (range 162.3-170.2),
**median peak full-process-tree RSS 68.7 MiB (range 66.8-70.3), about 54%
of the ~128 MiB target**. 1,000 files: median 6.21 s, median peak RSS 51.2
MiB. Every run's finding counts matched exactly; source files verified
byte-identical via SHA-256 manifest before and after every run; no
absolute path, digest, or username found in any raw report. Full
methodology and results in `benchmarks/README.md`. This is a measurement
on one machine, not a statistical benchmark or a universal guarantee.

### Security hardening

- Documented policy-file parsing threat model (no YAML, no code
  execution, strict typing, exit code `2` before any dataset is touched).
- Documented terminal-control-character and report-injection mitigations
  already implemented in v0.1 (`SYS004`, flat scalar-only evidence).
- Documented CI supply-chain posture (GitHub Actions pinned to full commit
  SHAs, least-privilege `contents: read`).

### Experimental / deferred

- **Near-duplicate (perceptual-hash) detection: deferred**, not
  implemented in this release. Evaluated against this project's own
  conditions for shipping it (opt-in, bounded memory/runtime, strong
  tests against rotation/resize/recompression, no heavy CV/ML dependency)
  and judged not confidently met on this cycle's timeline -- see
  `docs/design-decisions.md`. Deferring it is preferred over shipping a
  feature whose false-positive/negative behavior isn't well understood.
- **Concurrency: deferred.** The single-process design already meets the
  low-spec resource target with margin; multiprocessing/threading was not
  attempted this cycle (see `docs/design-decisions.md`).
- **Property-based testing/fuzzing framework and mutation-testing
  tooling: not added.** Covered instead by deliberately chosen
  boundary-value tests and a manual adversarial review of the
  highest-risk modules -- a narrower guarantee than tool-measured
  coverage, reported as such.
- **Metadata-table-driven datasets** (a `metadata.csv`/`.jsonl` label
  file) are out of scope for this release.

### External validation

No external user testing has been performed. A protocol exists at
`docs/user-testing-protocol.md` and is explicitly marked pending.

### Important limitations

- Exact-byte duplicate detection only; no perceptual similarity detection.
- No licensing, consent, bias, malware, NSFW, or semantic-label validation.
- This release candidate should be evaluated before the final v0.2.0
  release.

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
