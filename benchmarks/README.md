# Benchmark methodology and results

**Measured on one machine, at one point in time. Not a statistical
benchmark across hardware/OS variety, and not a claim that these numbers
hold on other machines, OS versions, storage types, or future package
versions.** Generated datasets and machine-specific result files are never
committed; only this document and the reusable scripts are.

## How to reproduce

Requires `psutil` (not a runtime dependency of the package -- install it
separately for this purpose only):

```
pip install imageset_guard-<version>-py3-none-any.whl psutil
python benchmarks/generate_workload.py 10000 /tmp/isg-bench-ds
python benchmarks/hash_manifest.py /tmp/isg-bench-ds write /tmp/manifest.txt
python benchmarks/run_benchmark.py <path-to-imageset-guard.exe-or-imageset-guard> \
    /tmp/isg-bench-ds /tmp/report.json /tmp/result.json
python benchmarks/hash_manifest.py /tmp/isg-bench-ds verify /tmp/manifest.txt
```

Repeat `run_benchmark.py` (against the *same*, unmodified generated
dataset) as many times as you want repetitions; each run's own JSON result
records its own wall time, peak process-tree RSS, exit code, and finding
counts.

## Workload

Deterministic (fixed seed), generated locally, no downloaded or
copyrighted assets: mixed JPEG/PNG/WebP, dimensions randomized
256-1280px, 3 deliberately corrupted files, 1 EXIF-bearing image, 1
EXIF+GPS-bearing image, and one exact duplicate of each supported kind
(same split+class, cross-class, cross-split) -- every duplicate copy keeps
its source's real extension, so none is an unintended format/extension
mismatch.

## Machine context (this run)

- CPU: Intel(R) Core(TM) i5-7200U @ 2.50GHz (2 cores / 4 logical processors)
- RAM: 7.9 GiB total
- Storage: system drive on a SanDisk SD8SN8U128G1027 SATA SSD
- OS: Windows 10 Home Single Language, version 10.0.19045 (Build 19045), 64-bit
- Python: 3.12.3
- Pillow: 12.3.0
- imageset-guard: installed from the built wheel (not the editable source
  checkout) into a clean virtual environment
- Command: `imageset-guard scan <dataset> --output report.json`

The installed console-script `.exe` on Windows is a thin launcher that
execs a child `python.exe`; peak memory below is measured across the
*whole* process tree, not the launcher alone.

## Results: 1,000 files (3 runs)

| Run | Wall time (s) | Throughput (files/s) | Peak process-tree RSS (MiB) |
|---|---|---|---|
| 1 | 6.21 | 161.1 | 47.5 |
| 2 | 6.26 | 159.7 | 51.2 |
| 3 | 6.11 | 163.6 | 55.8 |

Median duration: **6.21 s** (range 6.11-6.26). Median throughput: **161.1
files/s** (range 159.7-163.6). Median peak RSS: **51.2 MiB** (range
47.5-55.8).

## Results: 10,000 files (3 runs)

| Run | Wall time (s) | Throughput (files/s) | Peak process-tree RSS (MiB) |
|---|---|---|---|
| 1 | 61.62 | 162.3 | 70.3 |
| 2 | 58.74 | 170.2 | 66.8 |
| 3 | 59.00 | 169.5 | 68.7 |

Median duration: **59.00 s** (range 58.74-61.62). Median throughput:
**169.5 files/s** (range 162.3-170.2). Median peak RSS: **68.7 MiB**
(range 66.8-70.3).

## Acceptance check against the 128 MiB target

The v0.2 engineering target was "no more than ~128 MiB full-process-tree
peak RSS scanning a normal 10,000-image workload." Measured median: **68.7
MiB, about 54% of the target**, with no run exceeding 70.3 MiB. Peak RSS
did not scale linearly with dataset size (51.2 MiB at 1,000 files vs. 68.7
MiB at 10,000 -- a 10x file-count increase producing roughly a 1.3x memory
increase), consistent with the bounded, streaming design (one file open,
decoded, and closed at a time; SHA-256 in bounded chunks; the dataset
profile aggregated with running counts, not per-file records).

## Verification performed for every run

- Finding counts verified identical across all 3 repetitions at each size
  (`IMG003=3, DUP001=1, DUP002=1, DUP003=1, PRIV001=2, PRIV002=1`).
- `exit_code == 1` in every run (the deliberately planted errors), never a
  crash.
- Source dataset files verified byte-identical via a full SHA-256 manifest
  before the first run and after the last run at each size.
- Every report validated as parseable JSON.
- Every raw report text searched for a drive-letter path, a 64-hex-
  character digest, `"AppData"`, and the maintainer's username -- none
  found in any of the 6 reports.

## Cold/warm cache limitations

Each size's 3 repetitions ran back-to-back against the same
already-generated files, so the OS page/file cache was warm for runs 2
and 3 relative to run 1. This is disclosed, not corrected for; a genuinely
cold-cache first-run number would likely be slower on a spinning disk and
is not separately measured here.
