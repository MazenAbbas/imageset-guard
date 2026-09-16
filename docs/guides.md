# Practical guides

Every command below is exercised by this repository's own tests (see
`tests/test_acceptance_scenarios.py`), not just written for this document.

## Student: checking an assignment dataset

You have a folder of images organized by class and want to catch problems
before submitting or training.

```
imageset-guard doctor
imageset-guard scan ./my-assignment-dataset
```

If your dataset has no `train`/`validation`/`test` folders at all -- just
one folder per class -- say so explicitly:

```
imageset-guard scan ./my-assignment-dataset --layout class-only
```

Read the `Findings:` section top to bottom; each line names a file (when
applicable), a stable code, and a concise message. Exit code `0` means
`PASS` or `WARN` (nothing blocking); `1` means a policy-level problem
(`FAIL`) worth fixing before you submit.

## Data scientist: profiling a dataset before an experiment

You want to know the shape of your data -- class counts, formats, image
size range -- before training.

```
imageset-guard scan ./data --output report.json
```

Every scan includes a `profile` section (also printed in the terminal
summary) with file counts by split/class, format and color-mode counts,
width/height/aspect-ratio boundaries, empty classes, and a class-balance
ratio. These are facts, not judgments -- nothing is flagged as a problem
unless you configure a policy limit (see the data-engineer guide below).

## ML engineer: detecting train/test leakage

You want a hard guarantee that no exact-byte-identical image appears in
more than one split.

```
imageset-guard scan ./data
```

Any exact duplicate across `train`/`validation`/`test` produces a `DUP003`
finding (always an error) naming both the file and the split it also
appears in via `evidence.matches`. A duplicate within the same split and
class is `DUP001` (a warning: repeated weighting, not leakage); a
duplicate across classes in the same split is `DUP002` (an error:
conflicting labels for identical bytes). This is exact-byte matching --
resized, recompressed, or visually similar copies are not detected (see
[README.md's "Known limitations"](../README.md#known-limitations)).

## Data engineer: enforcing a policy in CI

You want a repeatable quality gate with a specific bar: minimum images per
class, a class-imbalance limit, and no GPS metadata allowed.

`policy.toml`:

```toml
schema_version = 1
min_images_per_class = 20
max_class_imbalance_ratio = 5.0
gps_policy = "forbid"
```

Validate the policy file itself first (fails fast, before any dataset scan,
with exit code `2` on a mistake):

```
imageset-guard policy-check policy.toml
```

Then run the gate in CI:

```
imageset-guard scan ./data --config policy.toml --output report.json --quiet
```

`--quiet` suppresses the human-readable summary so CI logs stay short; the
exit code (`0` pass/warn, `1` policy violation, `2` invalid config, `3`
incomplete/write failure, `4` internal error, `130` interrupted) is
unaffected, and `report.json` is written regardless for later inspection or
artifact upload. Parse `findings[].code` for the specific violations
(`POLICY003` for a too-small class, `POLICY004` for imbalance, `POLICY002`
for GPS presence).

## Instructor: applying one shared policy to many submissions

You have one `policy.toml` and many student submission folders to check the
same way.

```
imageset-guard policy-check policy.toml
for submission in ./submissions/*/; do
  imageset-guard scan "$submission" --config policy.toml \
    --output "./reports/$(basename "$submission").json" --quiet
  echo "$(basename "$submission"): exit $?"
done
```

Each `report.json` is deterministic and self-contained (no absolute paths,
no timestamps) -- safe to diff between two runs of the same submission, or
to collect across a whole class.
