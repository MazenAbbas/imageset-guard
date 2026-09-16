# ImageSet Guard

Local preflight checks for image datasets before training.

ImageSet Guard is a small, local command-line tool for image-classification
datasets laid out as `train/<class>/`, with optional `validation/<class>/`
and `test/<class>/` splits. It is meant to run **before** training starts,
to catch structural, integrity, and privacy-metadata problems early.

It does not use machine learning, does not require a GPU, does not require
network access, and does not upload any image anywhere. It is read-only: it
has no command that modifies, deletes, or moves files inside the dataset it
scans, and none is planned.

## Project status

This repository has completed the **Foundation and Contracts**, **Dataset
Discovery and Structure**, **Image Integrity and Privacy Inspection**, and
**Exact Duplicate and Leakage Detection**
phases. So far this includes: the
typed data models, exit-code contract, policy loader, path-safety checks,
the deterministic JSON report writer, and a discovery layer that walks a
dataset and reports its structure — splits, classes, misplaced files,
symbolic links, and cross-platform name-portability risks (Unicode
normalization collisions, case-fold collisions, reserved Windows names).
The inspection layer verifies and fully decodes static JPEG, PNG, and WebP
files, enforces pixel limits, compares detected content format with the
extension, and reports only the presence of EXIF/GPS metadata. The hashing
layer streams integrity-eligible files through SHA-256 and identifies
byte-identical files within one class, across classes, or across dataset
splits. Digests remain internal and never enter findings.

These layers are now composed by the public `imageset-guard scan` command.
It produces a real `PASS`, `WARN`, `FAIL`, or `INCOMPLETE` result, prints a
deterministic terminal summary, and can atomically write the canonical JSON
report outside the dataset root.

The project remains a pre-release (`0.1.0.dev0`). It has been exercised
locally on Windows with Python 3.12; the configured multi-platform CI matrix
still needs to run on the eventual GitHub repository before the first release.

## What ImageSet Guard is not

- Not a machine-learning tool. It never trains, infers, or uses embeddings.
- Not a duplicate/outlier detector based on visual similarity. The hashing
  layer considers exact byte identity only; resized, recompressed,
  cropped, or visually similar images are different to it.
- Not a legal or licensing checker. It cannot tell you a dataset is properly
  licensed or that consent was obtained.
- Not a content moderation or NSFW detection tool.
- Not a fixer. It never deletes, edits, or moves files in your dataset.
- A `PASS` result means the checks it runs
  found nothing to flag — not that the dataset is correct, unbiased, fair,
  legally clear, or free of every possible form of data leakage.

## Installation

Not yet published to PyPI. Once published, installation will be:

```
pip install imageset-guard
```

Until then, install from a local checkout into a virtual environment:

```
python -m venv .venv
.venv/bin/pip install .          # or .venv\Scripts\pip.exe install . on Windows
```

## Requirements

- Requires Python 3.11 or newer. CI tests Python 3.11 through 3.14; newer
  versions are not deliberately blocked, but are only actually verified
  once CI covers them.
- [Pillow](https://python-pillow.org/) is the only runtime dependency.

## Command-line usage

```
imageset-guard --version
imageset-guard scan DATASET_ROOT
imageset-guard scan DATASET_ROOT --config policy.toml
imageset-guard scan DATASET_ROOT --output report.json
```

`DATASET_ROOT` must exist, be a directory, and be readable. `--output`, if
given, must be a path ending in `.json`, and must not be equal to or located
inside `DATASET_ROOT`. `--config` points to a policy file — see
[Policy configuration](#policy-configuration) below.

The command always prints a human-readable result to standard output. With
`--output`, it also writes the canonical JSON report atomically. The report
path must be outside the dataset root; a report-write failure returns exit
code `3` and never leaves a partial report in place.

## Policy configuration

Policy is a small [TOML](https://toml.io/) file (no YAML, no plugins, no
scripting). In v1 the only recognized setting is:

```toml
max_pixels = 50_000_000
```

- `max_pixels` bounds the number of pixels an image may have before it is
  treated as a decompression-bomb-level safety problem. The project default
  is `50_000_000`. It must be a positive integer; it cannot be set to zero,
  a negative number, or disabled.
- Supported image formats in v1 are fixed and not configurable: JPEG, PNG,
  and WebP.
- A `train` split is always required; `validation` and `test` are always
  optional. This is fixed in v1 and not configurable.

## Finding and scan-error codes

Every finding and scan error the scan engine can produce is declared
once in `imageset_guard/codes.py`, together with its default message; no
code is ever reused for a second meaning.

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
| `SPLIT010` | structure | A symbolic link **or Windows junction/reparse mount point** was found and skipped — never followed. `evidence["link_type"]` says which. | warning |
| `SPLIT011` | structure | Two names collide under Unicode normalization (NFC vs NFD). | warning |
| `SPLIT012` | structure | Two names collide when case-folded. | warning |
| `SPLIT013` | structure | A name is a reserved Windows device name (CON, PRN, AUX, NUL, COM1-9, LPT1-9), with or without an extension or trailing dots/spaces. | warning |
| `SPLIT014` | structure | A recognized split name (`validation` or `test`) exists but is not a directory. | error |
| `IMG001` | integrity | A file inside a class directory has an unsupported extension; it will not be scanned in v1. | warning |
| `IMG002` | integrity | A non-regular filesystem entry (socket, FIFO, device, ...) inside a class directory was skipped; it is never opened. | warning |
| `IMG003` | integrity | Content is not recognized as an image. | error |
| `IMG004` | integrity | The image header was recognized, but verification or full pixel decoding failed. | error |
| `IMG005` | integrity | The detected content format does not match the filename extension, or is outside JPEG/PNG/WebP. | error |
| `IMG006` | integrity | The image exceeds the configured pixel limit or Pillow's decompression-bomb protection. | error |
| `IMG007` | integrity | The image is animated or multi-frame; v1 accepts static images only. | error |
| `IMG008` | integrity | Pillow emitted another decoder warning; its raw text is discarded. | warning |
| `PRIV001` | privacy | EXIF metadata is present; no values are reported. | warning |
| `PRIV002` | privacy | The EXIF GPSInfo tag is present; the GPS IFD and coordinates are not read or reported. | error |
| `DUP001` | leakage | Byte-identical files occur more than once in the same split and class. | warning |
| `DUP002` | leakage | Byte-identical files are assigned to different classes. | error |
| `DUP003` | leakage | Byte-identical files occur in different dataset splits. | error |
| `SYS001` | operational | Permission denied while accessing a path. | — (`ScanError`, not a `Finding`) |
| `SYS002` | operational | A path disappeared during the scan (a TOCTOU race, not a crash). | — (`ScanError`, not a `Finding`) |
| `SYS003` | operational | Any other OS-level failure while listing or inspecting a path. | — (`ScanError`, not a `Finding`) |
| `SYS004` | operational | An entry name cannot be represented safely in the report; it is skipped without being named. | — (`ScanError`, not a `Finding`) |
| `SYS005` | operational | A candidate changed or stopped naming the same regular file while being examined; the partial result is discarded. | — (`ScanError`, not a `Finding`) |

`SPLIT010`'s meaning was deliberately broadened from "symbolic link" to
"symbolic link or junction" while this project is still pre-release
(`0.dev0`); its code value did not change. `ScanError.message` is always
one of the fixed strings above — never raw OS exception text, which can
contain an absolute path or a username.

Candidate image extensions in v1 (case-insensitive during discovery):
`.jpg`, `.jpeg`, `.png`, `.webp`. Inspection trusts Pillow's content-based
format detection rather than the extension alone.

### Image inspection behavior

Inspection processes one candidate at a time and closes it before moving
to the next. It opens the file read-only, uses Pillow's `verify()` pass,
then rewinds and uses `load()` to force pixel decoding. Pillow documents
that an image must be reopened after `verify()` before loading; both passes
use the same already-open file descriptor here. Animated and other
multi-frame images are rejected in v1 rather than silently using only the
first frame.

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

### Exact duplicate and leakage behavior

Only files that inspection examined without an integrity error are eligible
for hashing. Privacy findings do not suppress hashing: an otherwise valid
image with EXIF or GPS metadata can still participate in duplicate checks.
Each eligible file is reopened read-only and streamed through SHA-256 in
bounded chunks. It is never loaded wholly into memory for hashing. The reopen
must match the descriptor identity, size, and modification time captured by
inspection; otherwise the partial hash is discarded and the scan becomes
`INCOMPLETE`.

The digest is an internal grouping key. Duplicate findings contain only the
relative path of a matching file, never the digest or an absolute path.
`DUP001` identifies repeated weighting inside one split/class; `DUP002`
identifies conflicting labels across classes; and `DUP003` identifies exact
train/validation/test leakage. One pair can correctly produce both `DUP002`
and `DUP003`. Results are sorted canonically and do not depend on caller input
order.

This is exact-byte detection, not perceptual matching. Any byte change can
produce a different digest even when two images look the same. SHA-256
equality here is evidence of byte identity for practical dataset checking;
it is not evidence of ownership, licensing, consent, or semantic correctness.

Implementation behavior follows Pillow's official documentation for
[`Image.open`, `verify`, and `load`](https://pillow.readthedocs.io/en/stable/reference/Image.html),
its [file-handling lifecycle](https://pillow.readthedocs.io/en/stable/reference/open_files.html),
and its [security guidance](https://pillow.readthedocs.io/en/stable/handbook/security.html).

### Completeness

A finding that depends on having seen *everything* in a directory (an
empty class, `train` having no classes at all, a class missing from
another split) is only ever emitted when that directory's listing was
fully enumerated with no operational failure. If even one entry could not
be classified (e.g. permission denied on one file among many), discovery
records a `ScanError` for it and continues with its siblings, but skips
any finding that would otherwise assume completeness — an incomplete scan
never gets rounded down to "confirmed empty" or "confirmed missing".
`ClassImageCount.is_complete` records this per class explicitly: when
`False`, `candidate_count` is a partial, best-effort count, not a
confirmed total.

## Results and exit codes

A normal scan result resolves to exactly one of these statuses, in precedence
order (highest wins). `ERROR` is reserved for an unexpected tool defect at the
process boundary; the CLI returns exit code `4` and does not fabricate a
dataset report in that case.

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
| `3` | `INCOMPLETE`, or an operational/filesystem failure (including a failed report write). |
| `4` | Unexpected internal error. |

## Design principles

- **Local only.** No network calls, ever.
- **Read-only.** Never edits, deletes, or moves files in the scanned
  dataset; there is no command that does, and none is planned.
- **No machine learning.** No embeddings, no models, no GPU.
- **Deterministic reports.** The same dataset and policy produce the same
  JSON report, byte for byte. Reports never contain timestamps, absolute
  paths, usernames, or environment/version metadata.
- **Privacy-aware by default.** Reports record whether sensitive metadata
  (such as GPS EXIF data) is present, never the sensitive values themselves.
- **Links are never followed *inside* a dataset, at any depth.** The
  dataset root you point the tool at is the one exception: it may itself
  be a symbolic link or a Windows junction to the real dataset, and is
  resolved before scanning starts. See [SECURITY.md](SECURITY.md) for the
  precise policy and its limits (this is not a defense against the
  filesystem changing while a scan is in progress).

## License

MIT. See [LICENSE](LICENSE).

## Security

See [SECURITY.md](SECURITY.md) for how to report a vulnerability, and for
an explicit statement of what this tool does and does not protect against.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
