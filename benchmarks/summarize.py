from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

bench_dir = Path(sys.argv[1])
for size in (1000, 10000):
    runs = [
        json.loads((bench_dir / f"result-{size}-run{i}.json").read_text(encoding="utf-8"))
        for i in (1, 2, 3)
    ]
    durations = [r["wall_seconds"] for r in runs]
    peaks = [r["peak_rss_mib"] for r in runs]
    throughputs = [size / r["wall_seconds"] for r in runs]
    print(f"--- {size} files ---")
    for i, (d, p, t) in enumerate(zip(durations, peaks, throughputs, strict=True), 1):
        print(f"  run {i}: {d:.2f}s  {t:.1f} files/s  peak {p:.1f} MiB")
    print(
        f"  median duration: {statistics.median(durations):.2f}s "
        f"(range {min(durations):.2f}-{max(durations):.2f})"
    )
    print(
        f"  median throughput: {statistics.median(throughputs):.1f} files/s "
        f"(range {min(throughputs):.1f}-{max(throughputs):.1f})"
    )
    print(
        f"  median peak RSS: {statistics.median(peaks):.1f} MiB "
        f"(range {min(peaks):.1f}-{max(peaks):.1f})"
    )
