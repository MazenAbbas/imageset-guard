# Contributing

Thanks for your interest in ImageSet Guard. This document describes how to
work on the codebase locally. The project is not yet published; this guide
applies to working from a local checkout.

## Scope discipline

Before proposing a change, check it against the project's non-goals in
`README.md`. This project deliberately stays a small, local, deterministic
preflight tool. Changes that add machine learning, network access, a
database, a web dashboard, or automatic file modification will not be
accepted, regardless of how useful they seem in isolation — they belong to
a different tool, not this one.

## Development setup

```
python -m venv .venv
.venv/bin/pip install -e ".[dev]"      # or .venv\Scripts\pip.exe on Windows
```

This installs the package in editable mode plus the development tools:
pytest, ruff, mypy, build, and twine.

## Required checks before submitting a change

All of the following must pass. None of them may be skipped or weakened to
make a change land:

```
ruff check .
mypy
pytest
python -m build
twine check dist/*
```

## Testing philosophy

- Write the test before the code it verifies. A test that never failed
  before the fix or feature existed does not prove anything.
- Every test must be traceable to a specific risk or documented behavior —
  not added to inflate a test count.
- Prefer real fixtures (generated images, real TOML files, real
  filesystem paths) over mocks. Mock only what genuinely cannot be
  exercised directly (e.g. simulating a permission failure).
- Any new finding code, exit code, or schema field is a contract change:
  it needs a test that pins its exact shape, not just a test that it
  "works".

## Determinism

Any change touching the JSON report writer must preserve byte-for-byte
determinism for a fixed input: same dataset and same policy must always
produce the same report bytes. No timestamps, absolute paths, usernames, or
environment/version metadata may enter the canonical report.

## Style

- Strict type hints everywhere; `mypy --strict` must pass with no
  suppressions unless a comment explains why one is unavoidable.
- Follow the existing module boundaries: data models (`models.py`),
  discovery data models (`discovery_models.py`), the finding/scan-error
  code registry (`codes.py`), dataset discovery (`discovery.py`), policy
  loading, path validation, serialization, rendering, and the CLI are
  separate concerns and should stay that way.

## Finding and scan-error codes

Every code (`SPLITxxx`, `IMGxxx`, `SYSxxx`, and any future prefix) is
declared exactly once in `codes.py`, with exactly one default message.
Never write a code or a default message as a bare string literal in
another module — import the constant. A code may have a
context-dependent *severity* (e.g. an empty class directory is an error in
`train` but a warning elsewhere) without that being a second meaning, but
it must never be reused for something semantically different. Adding a
code means adding it to `codes.py`, its message to `DEFAULT_MESSAGES`, and
a row to the finding-codes table in `README.md`.
