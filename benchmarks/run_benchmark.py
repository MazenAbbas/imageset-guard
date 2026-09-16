"""Reproducible benchmark runner for the installed imageset-guard wheel.

Not part of the imageset_guard package (excluded from the built wheel and
sdist) -- a development-only tool. Spawns the CLI as a real subprocess
and measures the *whole* Windows process tree: the installed
console-script .exe is a thin launcher that execs a child python.exe, and
the real work (and memory) happens in that child, not the launcher.

Requires ``psutil`` (dev-only; not a runtime dependency of the package).

Usage:
    python benchmarks/run_benchmark.py <cli_exe> <dataset_root> <output_json> <result_json>
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import time
from pathlib import Path

import psutil

POLL_INTERVAL_SECONDS = 0.02


def tree_rss(root: psutil.Process) -> int:
    total = 0
    for p in [root, *root.children(recursive=True)]:
        with contextlib.suppress(psutil.NoSuchProcess):
            total += p.memory_info().rss
    return total


def run_once(cli_exe: str, dataset_root: str, output_json: str) -> dict:
    cmd = [cli_exe, "scan", dataset_root, "--output", output_json]
    start = time.perf_counter()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    ps_proc = psutil.Process(proc.pid)

    peak_rss = 0
    samples = 0
    while proc.poll() is None:
        try:
            peak_rss = max(peak_rss, tree_rss(ps_proc))
            samples += 1
        except psutil.NoSuchProcess:
            break
        time.sleep(POLL_INTERVAL_SECONDS)

    stdout, stderr = proc.communicate()
    elapsed = time.perf_counter() - start

    report_path = Path(output_json)
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else None
    finding_counts: dict[str, int] = {}
    if report:
        for f in report.get("findings", []):
            finding_counts[f["code"]] = finding_counts.get(f["code"], 0) + 1

    return {
        "wall_seconds": elapsed,
        "exit_code": proc.returncode,
        "peak_rss_bytes": peak_rss,
        "peak_rss_mib": peak_rss / (1024 * 1024),
        "samples": samples,
        "report_status": report.get("status") if report else None,
        "report_summary": report.get("summary") if report else None,
        "finding_counts_by_code": finding_counts,
        "report_valid_json": report is not None,
        "stdout": stdout,
        "stderr": stderr,
    }


def main() -> None:
    cli_exe, dataset_root, output_json, result_json = sys.argv[1:5]
    result = run_once(cli_exe, dataset_root, output_json)
    Path(result_json).write_text(json.dumps(result, indent=2), encoding="utf-8")
    printable = {k: v for k, v in result.items() if k not in ("stdout", "stderr")}
    print(json.dumps(printable, indent=2))


if __name__ == "__main__":
    main()
