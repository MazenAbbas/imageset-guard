# ImageSet Guard

Local preflight checks for image datasets before training.

## What problem this solves

Training on a bad dataset wastes hours of compute before anyone notices.
ImageSet Guard runs **before** training starts and answers, deterministically
and locally: does this dataset have a structural problem, a corrupt or
mismatched file, leaked EXIF/GPS metadata, an exact-duplicate leak between
train and test, or a class-balance/size problem your policy cares about?

## Who it is for

- **Students** checking an assignment dataset before submitting or training.
- **Data scientists** profiling a dataset (format/mode/dimension facts,
  class balance) before an experiment.
- **ML engineers** catching train/validation/test leakage from exact
  duplicates before it inflates a metric.
- **Data engineers** adding a deterministic, scriptable quality gate to CI.
- **Instructors** applying one shared policy across many student
  submissions.

## What it is

A small, local command-line tool for image-classification datasets. It does
not use machine learning, does not require a GPU, does not require network
access after installation, and does not upload any image anywhere. It is
read-only: it has no command that modifies, renames, moves, repairs,
quarantines, or deletes files inside the dataset it scans, and none is
planned.

## Exact non-goals

ImageSet Guard does **not** guarantee, detect, or establish:

- Correct semantic labels (a mislabeled-but-valid image is invisible to it).
- Dataset ownership, licensing, or consent.
- Absence of bias.
- Absence of malware (beyond content that fails to decode as an image).
- Safe or appropriate image content (no NSFW/content moderation).
- Model quality, accuracy, or "AI-readiness" of any kind.
- Detection of every visually similar image -- duplicate detection is
  exact-byte only (see [Exact duplicate and leakage behavior](#exact-duplicate-and-leakage-behavior)).
- Completeness when part of the dataset could not be read (see
  [Completeness](#completeness)).

A `PASS` result means the checks this version runs found nothing to flag --
never "this dataset is correct, unbiased, fair, legally clear, or free of
every possible defect."

## Project status

The project is at `0.2.0rc1`, a release candidate. It is not the final
`v0.2.0` release and should not be treated as production-proof: it is
offered for evaluation and feedback. The full CI matrix (Windows, Linux,
and macOS across Python 3.11 through 3.14) is configured and green on this
repository. See [Known limitations](#known-limitations) and
[External validation status](#external-validation-status) before relying
on it for anything load-bearing.

## Installation

Not yet published to PyPI. Install from a release wheel:

```
pip install imageset_guard-0.2.0rc1-py3-none-any.whl
```

or from a local checkout into a virtual environment:

```
python -m venv .venv
.venv/bin/pip install .          # or .venv\Scripts\pip.exe install . on Windows
```

## Requirements

- Requires Python 3.11 or newer. CI tests Python 3.11 through 3.14.
- [Pillow](https://python-pillow.org/) is the only runtime dependency.
- Designed to work responsibly on a low-spec machine: 2 CPU cores, 8 GB RAM,
  no GPU, ordinary SSD/SATA storage, no network after install. See
  [Resource-conscious operation](#resource-conscious-operation).

## Quick start

```
pip install imageset_guard-0.2.0rc1-py3-none-any.whl
imageset-guard doctor                 # checks the install; never reads a dataset
imageset-guard example ./demo         # writes a tiny local example dataset
imageset-guard scan ./demo            # scan it
```

## Command-line usage

```
imageset-guard --version
imageset-guard doctor
imageset-guard example OUTPUT_DIR [--seed N]
imageset-guard policy-check policy.toml
imageset-guard scan DATASET_ROOT
imageset-guard scan DATASET_ROOT --config policy.toml
imageset-guard scan DATASET_ROOT --output report.json
imageset-guard scan DATASET_ROOT --layout class-only
imageset-guard scan DATASET_ROOT --quiet
imageset-guard scan DATASET_ROOT --progress
```

`DATASET_ROOT` must exist, be a directory, and be readable. `--output`, if
given, must be a path ending in `.json`, and must not be equal to or located
inside `DATASET_ROOT`. `--config` points to a policy file -- see
[Policy configuration](#policy-configuration). `--quiet` suppresses the
human-readable terminal summary only -- it never hides a fatal usage error,
and the exit code is unaffected. `--progress` writes periodic
`inspected N/M files` lines to stderr only; it never appears on stdout or in
the JSON report. Pressing Ctrl+C returns exit code `130` and never leaves a
partially written report at `--output`'s destination.

## Supported layouts

Select the layout explicitly with `--layout`; there is no automatic
detection, so a dataset is never silently reinterpreted.

**`split-class`** (default) -- `train` is required; `validation`/`test` are
optional:

```
DATASET_ROOT/
  train/
    cats/       a.jpg  b.png
    dogs/       c.webp
  validation/
    cats/       d.jpg
  test/
    dogs/       e.jpg
```

**`class-only`** -- no split directories at all (the layout torchvision's
`ImageFolder` and Hugging Face's single-directory `imagefolder` both use).
Every candidate is reported as if it were under an implicit `train` split:

```
DATASET_ROOT/
  cats/         a.jpg  b.png
  dogs/         c.webp
```

```
imageset-guard scan DATASET_ROOT --layout class-only
```

Metadata-table-driven datasets (a `metadata.csv`/`.jsonl` file mapping
filenames to labels, as Hugging Face's `imagefolder` also supports) are out
of scope for this release.

## Policy configuration

Policy is a small [TOML](https://toml.io/) file (no YAML, no plugins, no
scripting, no regular expressions). Every key is optional except that an
explicit `schema_version` must match the version this build understands (currently
`1`); an absent `schema_version` defaults to the current version, so a
v0.1-style file with only `max_pixels` still loads and behaves identically.
Unknown keys and invalid types are always rejected before any dataset is
scanned, with exit code `2`.

```toml
schema_version = 1
max_pixels = 50_000_000

min_images_per_class = 10
max_class_imbalance_ratio = 5.0
allowed_formats = ["JPEG", "PNG"]
allowed_modes = ["RGB"]
min_width = 64
max_width = 4096
min_height = 64
max_height = 4096
min_aspect_ratio = 0.5
max_aspect_ratio = 2.0
exif_policy = "forbid"   # "allow" (default) or "forbid"
gps_policy = "forbid"    # "allow" (default) or "forbid"
```

Validate a policy file on its own, without scanning any dataset:

```
imageset-guard policy-check policy.toml
```

Notes:

- `max_pixels` bounds the number of pixels an image may have before it is
  treated as a decompression-bomb-level safety problem. Default
  `50_000_000`; must be a positive integer.
- Every field beyond `max_pixels` is new in v0.2 and defaults to "no
  additional constraint" -- an absent field never changes v0.1 behavior.
- Supported image formats are fixed project constants, not extensible:
  JPEG, PNG, WebP. `allowed_formats` may only *narrow* this set.
- A `train` split is always required in the `split-class` layout;
  `validation`/`test` are always optional. This is fixed and not
  configurable.
- **A policy violation never changes the meaning or severity of an
  existing `SPLIT`/`IMG`/`PRIV`/`DUP` finding code.** Every policy rule
  produces a distinct `POLICYxxx` code instead (see the table below).

## Finding and scan-error codes

Every finding and scan error is declared once in `imageset_guard/codes.py`,
together with its default message; no code is ever reused for a second
meaning.

| Code | Category | Meaning | Severity |
|---|---|---|---|
| `SPLIT001` | structure | The required `train` split is missing. | error |
| `SPLIT002` | structure | `train` exists but is not a directory. | error |
| `SPLIT003` | structure | `train` contains no class directories. | error |
| `SPLIT004` | structure | A class directory has no candidate image files. | error in `train`, warning in `validation`/`test` |
| `SPLIT005` | structure | A class exists in an optional split but not in `train`. | error |
| `SPLIT006` | structure | A class exists in `train` but is missing from a present optional split. | warning |
| `SPLIT007` | structure | An image-like file sits directly in a split directory, not inside a class directory. | warning |
| `SPLIT008` | structure | An image-like file sits directly at the dataset root. | warning |
| `SPLIT009` | structure | A top-level directory is not `train`/`validation`/`test`; it was not scanned. | warning |
| `SPLIT010` | structure | A symbolic link **or Windows junction/reparse mount point** was found and skipped -- never followed. `evidence["link_type"]` says which. | warning |
| `SPLIT011` | structure | Two names collide under Unicode normalization (NFC vs NFD). | warning |
| `SPLIT012` | structure | Two names collide when case-folded. | warning |
| `SPLIT013` | structure | A name is a reserved Windows device name (CON, PRN, AUX, NUL, COM1-9, LPT1-9), with or without an extension or trailing dots/spaces. | warning |
| `SPLIT014` | structure | A recognized split name (`validation` or `test`) exists but is not a directory. | error |
| `IMG001` | integrity | A file inside a class directory has an unsupported extension; it will not be scanned. | warning |
| `IMG002` | integrity | A non-regular filesystem entry (socket, FIFO, device, ...) inside a class directory was skipped; it is never opened. | warning |
| `IMG003` | integrity | Content is not recognized as an image. | error |
| `IMG004` | integrity | The image header was recognized, but verification or full pixel decoding failed. | error |
| `IMG005` | integrity | The detected content format does not match the filename extension, or is outside JPEG/PNG/WebP. | error |
| `IMG006` | integrity | The image exceeds the configured pixel limit or Pillow's decompression-bomb protection. | error |
| `IMG007` | integrity | The image is animated or multi-frame; static images only are supported. | error |
| `IMG008` | integrity | Pillow emitted another decoder warning; its raw text is discarded. | warning |
| `PRIV001` | privacy | EXIF metadata is present; no values are reported. | warning |
| `PRIV002` | privacy | The EXIF GPSInfo tag is present; the GPS IFD and coordinates are not read or reported. | error |
| `DUP001` | leakage | Byte-identical files occur more than once in the same split and class. | warning |
| `DUP002` | leakage | Byte-identical files are assigned to different classes. | error |
| `DUP003` | leakage | Byte-identical files occur in different dataset splits. | error |
| `POLICY001` | policy | EXIF metadata is present and the policy's `exif_policy` is `"forbid"`. Fires *in addition to* `PRIV001`. | error |
| `POLICY002` | policy | GPS metadata is present and the policy's `gps_policy` is `"forbid"`. Fires *in addition to* `PRIV002`. | error |
| `POLICY003` | policy | A class has fewer accepted images than the policy's `min_images_per_class`. | error |
| `POLICY004` | policy | The dataset's largest:smallest non-empty class ratio exceeds `max_class_imbalance_ratio`. | error |
| `POLICY005` | policy | The image's detected format is not in `allowed_formats`. | error |
| `POLICY006` | policy | The image's Pillow color mode is not in `allowed_modes`. | error |
| `POLICY007` | policy | The image's width is outside `min_width`/`max_width`. | error |
| `POLICY008` | policy | The image's height is outside `min_height`/`max_height`. | error |
| `POLICY009` | policy | The image's aspect ratio is outside `min_aspect_ratio`/`max_aspect_ratio`. | error |
| `SYS001` | operational | Permission denied while accessing a path. | -- (`ScanError`, not a `Finding`) |
| `SYS002` | operational | A path disappeared during the scan (a TOCTOU race, not a crash). | -- (`ScanError`, not a `Finding`) |
| `SYS003` | operational | Any other OS-level failure while listing or inspecting a path. | -- (`ScanError`, not a `Finding`) |
| `SYS004` | operational | An entry name cannot be represented safely in the report; it is skipped without being named. | -- (`ScanError`, not a `Finding`) |
| `SYS005` | operational | A candidate changed or stopped naming the same regular file while being examined; the partial result is discarded. | -- (`ScanError`, not a `Finding`) |

`SPLIT010`'s meaning was deliberately broadened from "symbolic link" to
"symbolic link or junction" while this project is still pre-release
(`0.2.0rc1`); its code value did not change. `ScanError.message` is always
one of the fixed strings above -- never raw OS exception text, which can
contain an absolute path or a username.

Candidate image extensions (case-insensitive during discovery): `.jpg`,
`.jpeg`, `.png`, `.webp`. Inspection trusts Pillow's content-based format
detection rather than the extension alone.

### Image inspection behavior

Inspection processes one candidate at a time and closes it before moving to
the next. It opens the file read-only, uses Pillow's `verify()` pass, then
rewinds and uses `load()` to force pixel decoding. Pillow documents that an
image must be reopened after `verify()` before loading; both passes use the
same already-open file descriptor here. Animated and other multi-frame
images are rejected rather than silently using only the first frame.

`max_pixels` is checked without changing Pillow's process-wide
`Image.MAX_IMAGE_PIXELS`. Pillow's own `DecompressionBombWarning` and
`DecompressionBombError` are also failures. ImageSet Guard never enables
`LOAD_TRUNCATED_IMAGES`; if another library has enabled that process-wide
escape hatch, inspection refuses to continue rather than weakening strict
decoding silently.

An invalid, oversized, mismatched, or multi-frame file counts as examined:
the tool reached a deterministic conclusion about its data. A file blocked
by permission, disappearance, replacement, or another filesystem failure
does not count as examined and produces a `ScanError` instead.

### Dataset profile

Every scan also produces a deterministic **profile** of observed facts --
separate from policy judgment (see [Policy configuration](#policy-configuration)):
file counts by split and by class, format/mode counts, width/height/aspect-
ratio boundaries (exact min/max, computed with bounded streaming
aggregation -- no percentile estimation, no per-image record retained),
empty classes, and a class-balance ratio. `complete` is `false` whenever
any subtree could not be fully read, so a partial scan is never rounded up
to a confident fact. The profile never contains a decoded image, a file
path, or a digest.

### Exact duplicate and leakage behavior

Only files that inspection examined without an integrity error are eligible
for hashing. A policy violation (a `POLICYxxx` finding) never blocks
hashing -- only an `IMG00x`/integrity-error finding does. Privacy findings
also never suppress hashing: an otherwise valid image with EXIF or GPS
metadata can still participate in duplicate checks. Each eligible file is
reopened read-only and streamed through SHA-256 in bounded chunks. It is
never loaded wholly into memory for hashing. The reopen must match the
descriptor identity, size, and modification time captured by inspection;
otherwise the partial hash is discarded and the scan becomes `INCOMPLETE`.

The digest is an internal grouping key. Duplicate findings contain only the
relative path of a matching file, never the digest or an absolute path.
`DUP001` identifies repeated weighting inside one split/class; `DUP002`
identifies conflicting labels across classes; and `DUP003` identifies exact
train/validation/test leakage. One pair can correctly produce both `DUP002`
and `DUP003`. Results are sorted canonically and do not depend on caller
input order.

This is **exact-byte detection, not perceptual matching**. Any byte change
can produce a different digest even when two images look the same.
SHA-256 equality here is evidence of byte identity for practical dataset
checking; it is not evidence of ownership, licensing, consent, or semantic
correctness. Perceptual/near-duplicate detection was evaluated for this
release and deliberately deferred -- see [CHANGELOG.md](CHANGELOG.md) for
why.

Implementation behavior follows Pillow's official documentation for
[`Image.open`, `verify`, and `load`](https://pillow.readthedocs.io/en/stable/reference/Image.html),
its [file-handling lifecycle](https://pillow.readthedocs.io/en/stable/reference/open_files.html),
and its [security guidance](https://pillow.readthedocs.io/en/stable/handbook/security.html).

### Completeness

A finding that depends on having seen *everything* in a directory (an empty
class, `train` having no classes at all, a class missing from another
split) is only ever emitted when that directory's listing was fully
enumerated with no operational failure. If even one entry could not be
classified (e.g. permission denied on one file among many), discovery
records a `ScanError` for it and continues with its siblings, but skips any
finding that would otherwise assume completeness -- an incomplete scan
never gets rounded down to "confirmed empty" or "confirmed missing".
`ClassImageCount.is_complete` (and the profile's own `complete` field)
record this explicitly: when `false`, the corresponding count is a partial,
best-effort figure, not a confirmed total.

## Results and exit codes

A normal scan result resolves to exactly one of these statuses, in
precedence order (highest wins). `ERROR` is reserved for an unexpected tool
defect at the process boundary; the CLI returns exit code `4` and does not
fabricate a dataset report in that case.

| Status | Meaning |
|---|---|
| `ERROR` | Reserved process condition for an unexpected internal defect; never serialized as a normal `ScanResult`. |
| `INCOMPLETE` | One or more files could not be examined (e.g. permission denied, a file disappeared during the scan). |
| `FAIL` | The scan completed and policy violations exist. |
| `WARN` | The scan completed; warnings exist but policy passes. |
| `PASS` | The scan completed with zero warnings or errors. |

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Completed: `PASS` or `WARN`. |
| `1` | Completed: `FAIL` (policy violations). |
| `2` | Invalid command-line usage or invalid policy configuration. |
| `3` | `INCOMPLETE`, or an operational/filesystem failure (including a failed report write, or a failed `doctor` environment check). |
| `4` | Unexpected internal error. |
| `130` | Interrupted (Ctrl+C). New in v0.2, additive -- 0-4 keep their v0.1 meanings unchanged. |

## Terminal example

```
$ imageset-guard scan ./demo
Result: PASS
Files examined: 8
Scan errors: 0
Findings: 0 error, 0 warning, 0 info

Profile:
  Candidates: 8  Accepted: 8  Rejected: 0
  Files by split: train=8
  Classes: 2
  Class-balance ratio (largest:smallest): 1.00
  Formats: PNG=8
  Width: 64-64  Height: 64-64
```

## JSON / CI example

```
imageset-guard scan ./data --config policy.toml --output report.json --quiet
echo "exit code: $?"
```

```json
{
  "report_schema_version": 1,
  "status": "pass",
  "summary": { "examined_file_count": 8, "scan_error_count": 0, "finding_counts_by_severity": {"error": 0, "info": 0, "warning": 0} },
  "findings": [],
  "scan_errors": [],
  "profile": { "candidate_count": 8, "accepted_count": 8, "rejected_count": 0, "file_count_by_split": {"train": 8}, "...": "..." }
}
```

`report_schema_version` and `profile` are the only keys v0.2 adds; every
key/shape v0.1 defined is unchanged (see the golden compatibility tests in
`tests/test_v01_compatibility.py`). A future breaking report change would
bump `report_schema_version` and document a migration; it has not happened
yet.

## Resource-conscious operation

Designed for a low-spec machine (2 CPU cores, 8 GB RAM, no GPU, ordinary
SSD/SATA storage, no network after install): sequential, single-process
scanning; one file opened, decoded, and closed at a time; SHA-256 hashing
in bounded 1 MiB chunks; the dataset profile aggregated with bounded,
streaming counters (no per-image record retained). No concurrency was
added in v0.2 -- it was evaluated and deferred because the measured
single-process performance did not justify the added complexity risk to
correctness/determinism (see [CHANGELOG.md](CHANGELOG.md)).

Measured, repeated, synthetic-workload results on one Windows laptop are
in `CHANGELOG.md` and `benchmarks/README.md` -- **measured on one machine,
not a universal guarantee.**

## Windows / macOS / Linux notes

- Windows: junctions and NTFS reparse mount points are detected and never
  followed, in addition to symbolic links; Windows-reserved device names
  (`CON`, `NUL`, ...) are flagged as a portability risk.
- All three: Unicode NFC/NFD normalization collisions and case-fold
  collisions between sibling names are flagged, since some filesystems
  treat them as the same name and some do not.
- CI runs the full test suite and the packaging/install checks on Windows,
  Ubuntu, and macOS, across Python 3.11-3.14, on every push.

## Known limitations

- Exact-byte duplicate detection only; no perceptual/near-duplicate
  detection in this release (evaluated and deferred, see CHANGELOG).
- No licensing, consent, bias, malware, NSFW, or semantic-label validation.
- `class-only` and `split-class` are the only two supported layouts;
  metadata-table-driven datasets are out of scope.
- Progress reporting covers the inspection phase only, not hashing.
- This release candidate should be evaluated before the final `v0.2.0`
  release.

## External validation status

The scenarios in `tests/test_acceptance_scenarios.py` are executable,
locally-reproducible stand-ins for five real workflows (student, data
scientist, ML engineer, data engineer/CI, instructor). They are not a
substitute for real external user feedback. A user-testing protocol for
that feedback exists at `docs/user-testing-protocol.md` and has **not**
been executed -- no external user feedback is claimed anywhere in this
project.

## Design principles

- **Local only.** No network calls, ever.
- **Read-only.** Never edits, deletes, moves, renames, or repairs files in
  the scanned dataset; there is no command that does, and none is planned.
- **No machine learning.** No embeddings, no models, no GPU.
- **Deterministic reports.** The same dataset and policy produce the same
  JSON report, byte for byte. Reports never contain timestamps, absolute
  paths, usernames, or environment/version metadata.
- **Privacy-aware by default.** Reports record whether sensitive metadata
  (such as GPS EXIF data) is present, never the sensitive values themselves.
- **Facts before judgment.** The dataset profile reports observed facts;
  only an explicit, user-configured policy turns a fact into a finding.
- **Links are never followed *inside* a dataset, at any depth.** The
  dataset root you point the tool at is the one exception: it may itself
  be a symbolic link or a Windows junction to the real dataset, and is
  resolved before scanning starts. See [SECURITY.md](SECURITY.md) for the
  precise policy and its limits (this is not a defense against the
  filesystem changing while a scan is in progress).

## Practical guides

See [docs/guides.md](docs/guides.md) for the student, data-scientist,
ML-engineer, data-engineer/CI, and instructor workflows, each using
commands actually exercised by this repository's tests.

## License

MIT. See [LICENSE](LICENSE).

## Security

See [SECURITY.md](SECURITY.md) for how to report a vulnerability, and for
an explicit statement of what this tool does and does not protect against.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Changelog

See [CHANGELOG.md](CHANGELOG.md).
