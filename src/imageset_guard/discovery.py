"""Dataset structure discovery (Phase 2).

Walks a dataset root and reports its structure -- which splits and classes
exist, which files look like image candidates by extension, and which
files or directories are misplaced, missing, or portability-risky. It
never opens image content and never modifies anything on disk. It never
follows a symbolic link or a Windows junction/reparse mount point found
*inside* the dataset root, at any depth -- the root argument itself is the
one exception, since the caller's chosen root may itself legitimately be
a link to the real dataset; see :func:`discover`.

Every OS-level access (listing a directory, classifying an entry) is
wrapped so a permission failure or a path vanishing mid-scan becomes a
:class:`~imageset_guard.models.ScanError` and lets the walk continue,
rather than crashing or silently stopping. ``ScanError.message`` is always
a fixed registry string -- never the raw OS exception text, which can
contain an absolute path or a username.

Because a failure can happen at any point in the walk, this module tracks
*enumeration completeness* explicitly and never turns an incomplete
listing into a false structural claim: an unreadable subdirectory makes a
class's candidate count partial (``ClassImageCount.is_complete=False``)
rather than "confirmed empty", and an unreadable split makes
cross-split class comparisons simply not run, rather than reporting a
class as missing or extra based on a set we know is incomplete.
"""

from __future__ import annotations

import os
import stat
import unicodedata
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final, Literal, NamedTuple

from imageset_guard import codes
from imageset_guard.discovery_models import CANDIDATE_EXTENSIONS as CANDIDATE_EXTENSIONS
from imageset_guard.discovery_models import (
    ClassImageCount,
    DiscoveredImageCandidate,
    DiscoveryResult,
)
from imageset_guard.models import Category, Finding, ScanError, Severity
from imageset_guard.models import validate_relative_path as _validate_relative_path

_VALID_SPLITS: Final[tuple[str, ...]] = ("train", "validation", "test")
_OPTIONAL_SPLITS: Final[tuple[str, ...]] = ("validation", "test")

#: The two dataset layouts v0.2 can interpret unambiguously:
#: ``split-class`` is ``<split>/<class>/<image>`` (v0.1's only layout);
#: ``class-only`` is ``<class>/<image>`` with no split directories at all
#: (the layout torchvision's ``ImageFolder`` and Hugging Face's
#: single-directory ``imagefolder`` both use). Selecting ``class-only``
#: treats the whole dataset root as one implicit ``train`` split -- every
#: candidate's reported ``split`` is ``"train"``, exactly as if the class
#: directories had been placed under a literal ``train/`` folder.
Layout = Literal["split-class", "class-only"]

_WINDOWS_RESERVED_STEMS: Final[frozenset[str]] = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

_EntryKind = Literal["symlink", "junction", "dir", "file", "other"]
_LINK_KINDS: Final[frozenset[str]] = frozenset({"symlink", "junction"})


class _DiscoveryState:
    """Mutable accumulator threaded through one ``discover()`` call."""

    def __init__(self) -> None:
        self.findings: list[Finding] = []
        self.scan_errors: list[ScanError] = []
        self.candidates: list[DiscoveredImageCandidate] = []
        self.class_dirs_by_split: dict[str, set[str]] = {}
        self.split_direct_level_complete: dict[str, bool] = {}
        self.class_subtree_complete: dict[tuple[str, str], bool] = {}


class _SplitEnumeration(NamedTuple):
    class_names: set[str]
    direct_level_complete: bool


def discover(dataset_root: Path, *, layout: Layout = "split-class") -> DiscoveryResult:
    """Discover the structure of the dataset rooted at ``dataset_root``.

    ``layout`` selects how ``dataset_root`` itself is interpreted --
    ``"split-class"`` (the default, v0.1's only layout) expects
    ``train``/``validation``/``test`` subdirectories; ``"class-only"``
    expects class directories directly under ``dataset_root`` with no
    split concept at all, reported as a single implicit ``train`` split.
    There is no automatic layout detection: the caller (the CLI) must
    choose explicitly, so a dataset is never silently reinterpreted.

    ``dataset_root`` is resolved to an absolute, canonical path internally
    (it may be given as relative, e.g. ``Path(".")``). This is the one
    deliberate exception to "never follow a link": the caller's own chosen
    root is allowed to itself be a symbolic link or a junction pointing at
    the real dataset -- resolving it is what makes that work. The
    "never follow a link" policy applies only to entries found *during*
    the walk, i.e. everything encountered strictly inside this root, never
    to the root argument itself.

    This tool is not a security boundary, and this is not exempt from
    check-then-use TOCTOU: nothing stops the filesystem from changing
    between this resolution step and the walk that follows, or during the
    walk itself. Scan a dataset that is stable and not being concurrently
    modified.

    If even resolving the path fails (e.g. a permission error on some
    component, or a symlink loop), that becomes a single ``ScanError``
    rather than an unhandled exception.
    """
    state = _DiscoveryState()
    try:
        dataset_root = dataset_root.resolve()
    except (OSError, RuntimeError) as exc:
        # RuntimeError: Python 3.11/3.12's pathlib raises this (not
        # OSError) for a symlink loop. Same treatment either way.
        state.scan_errors.append(_scan_error_for_exception(exc, None, "walk"))
        return DiscoveryResult(
            candidates=(), findings=(), scan_errors=tuple(state.scan_errors), class_counts=()
        )

    if layout == "class-only":
        _discover_root_class_only(dataset_root, state)
    else:
        _discover_root(dataset_root, state)

    class_counts = _build_class_counts(state)

    return DiscoveryResult(
        candidates=tuple(sorted(state.candidates, key=lambda c: c.relative_path)),
        findings=tuple(sorted(state.findings, key=_finding_sort_key)),
        scan_errors=tuple(sorted(state.scan_errors, key=_scan_error_sort_key)),
        class_counts=class_counts,
    )


def _finding_sort_key(finding: Finding) -> tuple[str, str, str]:
    return (finding.relative_path or "", finding.code, finding.message)


def _scan_error_sort_key(error: ScanError) -> tuple[str, str, str]:
    return (error.relative_path or "", error.code, error.operation)


def _build_class_counts(state: _DiscoveryState) -> tuple[ClassImageCount, ...]:
    counts: dict[tuple[str, str], int] = {}
    for split, class_names in state.class_dirs_by_split.items():
        for class_name in class_names:
            counts[(split, class_name)] = 0
    for candidate in state.candidates:
        key = (candidate.split, candidate.class_name)
        counts[key] = counts.get(key, 0) + 1
    return tuple(
        ClassImageCount(
            split=split,
            class_name=class_name,
            candidate_count=count,
            is_complete=state.class_subtree_complete.get((split, class_name), True),
        )
        for (split, class_name), count in sorted(counts.items())
    )


# ---------------------------------------------------------------------------
# Pure classification predicates -- no filesystem access, fully testable
# with plain strings/ints/fakes regardless of what this machine's real
# filesystem will let a test actually create.
# ---------------------------------------------------------------------------


def is_windows_reserved_name(name: str) -> bool:
    """Is ``name`` a reserved Windows device name?

    Windows strips trailing dots and spaces before comparing, and only the
    portion before the first remaining dot matters -- so ``"CON.txt"``,
    ``"CON."``, and ``"con "`` are all reserved, but ``"MYCON"`` is not.
    Only COM1-9 and LPT1-9 are reserved (not COM0 or COM10+).
    """
    stripped = name.rstrip(" .")
    if not stripped:
        return False
    stem = stripped.split(".", 1)[0].upper()
    return stem in _WINDOWS_RESERVED_STEMS


def _find_collisions(
    names: Sequence[str], key: Callable[[str], str]
) -> list[tuple[str, str]]:
    """Pair up distinct names from ``names`` that share the same ``key``.

    Each later name is compared against the first-seen name with that key;
    for N>2 colliding names this yields N-1 pairs, not every combination.
    """
    seen: dict[str, str] = {}
    collisions: list[tuple[str, str]] = []
    for name in names:
        k = key(name)
        existing = seen.get(k)
        if existing is not None and existing != name:
            first, second = sorted((existing, name))
            collisions.append((first, second))
        else:
            seen.setdefault(k, name)
    return collisions


def find_case_fold_collisions(names: Sequence[str]) -> list[tuple[str, str]]:
    """Find sibling name pairs that collide once case-folded."""
    return _find_collisions(names, str.casefold)


def find_nfc_collisions(names: Sequence[str]) -> list[tuple[str, str]]:
    """Find sibling name pairs that collide once normalized to NFC."""
    return _find_collisions(names, lambda n: unicodedata.normalize("NFC", n))


def is_representable_relative_path(candidate: str) -> bool:
    """Can ``candidate`` safely become a ``relative_path`` on a report model?

    Delegates to the exact same validator
    :class:`~imageset_guard.models.Finding`/``ScanError``/
    ``DiscoveredImageCandidate`` already enforce in their own
    constructors, so this can never drift out of sync with what would
    actually be accepted there. Used to filter out a hostile or
    unrepresentable entry name *before* it ever reaches one of those
    constructors, rather than letting the ``ValueError`` crash the whole
    walk.
    """
    try:
        _validate_relative_path(candidate)
    except ValueError:
        return False
    return True


def _is_mount_point_reparse_tag(tag: int) -> bool:
    mount_point_tag = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", None)
    return mount_point_tag is not None and tag == mount_point_tag


def _is_junction(entry: os.DirEntry[str]) -> bool:
    """Is ``entry`` a Windows junction/mount-point reparse point?

    ``DirEntry.is_symlink()`` does not detect this -- a junction is a
    different NTFS reparse type. Prefers ``DirEntry.is_junction()``
    (Python 3.12+, always False on non-Windows); falls back to inspecting
    ``stat(follow_symlinks=False).st_reparse_tag`` directly for 3.11 on
    Windows (harmlessly always False elsewhere, since neither the
    attribute nor the ``stat`` module constant exists off Windows).
    """
    is_junction_method = getattr(entry, "is_junction", None)
    if is_junction_method is not None:
        return bool(is_junction_method())
    st = entry.stat(follow_symlinks=False)
    reparse_tag = getattr(st, "st_reparse_tag", 0)
    return _is_mount_point_reparse_tag(reparse_tag)


# ---------------------------------------------------------------------------
# OS access wrappers -- every real filesystem touch goes through these,
# so TOCTOU failures have one place to become ScanErrors, and the message
# is always the fixed registry text, never raw OS exception text (which
# can carry an absolute path or a username).
# ---------------------------------------------------------------------------


def _classify(entry: os.DirEntry[str]) -> _EntryKind:
    """Classify ``entry`` without following any symlink or junction.

    May raise OSError (a TOCTOU race or a permission failure).
    """
    if entry.is_symlink():
        return "symlink"
    if _is_junction(entry):
        return "junction"
    if entry.is_dir(follow_symlinks=False):
        return "dir"
    if entry.is_file(follow_symlinks=False):
        return "file"
    return "other"


def _list_dir(
    path: Path, relative_path: str | None, state: _DiscoveryState
) -> tuple[list[os.DirEntry[str]], bool] | None:
    """List ``path``'s children, sorted by name.

    Records a ScanError and returns ``None`` if the directory cannot be
    listed at all. Otherwise returns ``(safe_entries, all_representable)``:
    any entry whose name cannot safely become part of a canonical
    ``relative_path`` (see :func:`is_representable_relative_path`) is
    filtered out here -- before it can ever reach a
    ``Finding``/``ScanError``/``DiscoveredImageCandidate`` constructor and
    raise -- and reported instead as a single
    ``SYS_UNREPRESENTABLE_NAME`` ScanError that never names it.
    ``all_representable`` is ``False`` if that happened to at least one
    entry; the caller must then treat this directory's enumeration as
    incomplete, exactly like any other partial listing.
    """
    try:
        with os.scandir(path) as it:
            entries = list(it)
    except OSError as exc:
        state.scan_errors.append(_scan_error_for_exception(exc, relative_path, "walk"))
        return None

    entries.sort(key=lambda e: e.name)

    safe_entries: list[os.DirEntry[str]] = []
    all_representable = True
    for entry in entries:
        if is_representable_relative_path(_join(relative_path, entry.name)):
            safe_entries.append(entry)
        else:
            state.scan_errors.append(
                ScanError(
                    code=codes.SYS_UNREPRESENTABLE_NAME,
                    message=codes.DEFAULT_MESSAGES[codes.SYS_UNREPRESENTABLE_NAME],
                    relative_path=relative_path,
                    operation="walk",
                )
            )
            all_representable = False

    return safe_entries, all_representable


def _scan_error_for_exception(
    exc: OSError | RuntimeError, relative_path: str | None, operation: str
) -> ScanError:
    """Build the fixed-message ScanError for an OS-level failure.

    Accepts ``RuntimeError`` too: on Python 3.11/3.12,
    ``pathlib.Path.resolve()`` can raise ``RuntimeError`` (not ``OSError``)
    for a symlink loop. Neither ``PermissionError`` nor
    ``FileNotFoundError`` is a ``RuntimeError``, so it always falls
    through to the generic ``SYS_STAT_OR_WALK_FAILURE`` code below -- and,
    like every other branch here, only ever the fixed registry message,
    never ``str(exc)``.
    """
    if isinstance(exc, PermissionError):
        code = codes.SYS_PERMISSION_DENIED
    elif isinstance(exc, FileNotFoundError):
        code = codes.SYS_PATH_VANISHED
    else:
        code = codes.SYS_STAT_OR_WALK_FAILURE
    return ScanError(
        code=code,
        message=codes.DEFAULT_MESSAGES[code],
        relative_path=relative_path,
        operation=operation,  # type: ignore[arg-type]
    )


def _join(parent: str | None, name: str) -> str:
    return name if parent is None else f"{parent}/{name}"


# ---------------------------------------------------------------------------
# Portability findings: name collisions and reserved names, checked once
# per directory listing (siblings only -- collisions across unrelated
# directories are not a real filesystem risk).
# ---------------------------------------------------------------------------


def _portability_findings(
    entries: list[os.DirEntry[str]], relative_path: str | None
) -> list[Finding]:
    names = [e.name for e in entries]
    findings: list[Finding] = []

    for first, second in find_nfc_collisions(names):
        findings.append(
            Finding(
                code=codes.SPLIT_UNICODE_NORMALIZATION_COLLISION,
                severity=Severity.WARNING,
                category=Category.STRUCTURE,
                message=codes.DEFAULT_MESSAGES[codes.SPLIT_UNICODE_NORMALIZATION_COLLISION],
                relative_path=relative_path,
                evidence={"name_a": first, "name_b": second},
                remediation="Rename one of the two entries so they no longer collide "
                "under Unicode normalization.",
            )
        )

    for first, second in find_case_fold_collisions(names):
        findings.append(
            Finding(
                code=codes.SPLIT_CASE_FOLD_COLLISION,
                severity=Severity.WARNING,
                category=Category.STRUCTURE,
                message=codes.DEFAULT_MESSAGES[codes.SPLIT_CASE_FOLD_COLLISION],
                relative_path=relative_path,
                evidence={"name_a": first, "name_b": second},
                remediation="Rename one of the two entries so they no longer collide "
                "on a case-insensitive filesystem.",
            )
        )

    for name in names:
        if is_windows_reserved_name(name):
            findings.append(
                Finding(
                    code=codes.SPLIT_WINDOWS_RESERVED_NAME,
                    severity=Severity.WARNING,
                    category=Category.STRUCTURE,
                    message=codes.DEFAULT_MESSAGES[codes.SPLIT_WINDOWS_RESERVED_NAME],
                    relative_path=_join(relative_path, name),
                    evidence={"name": name},
                    remediation="Rename this entry; it will fail or behave unexpectedly "
                    "on Windows.",
                )
            )

    return findings


def _is_candidate_extension(name: str) -> bool:
    return Path(name).suffix.lower() in CANDIDATE_EXTENSIONS


def _link_skipped_finding(relative_path: str, link_type: str) -> Finding:
    return Finding(
        code=codes.SPLIT_LINK_SKIPPED,
        severity=Severity.WARNING,
        category=Category.STRUCTURE,
        message=codes.DEFAULT_MESSAGES[codes.SPLIT_LINK_SKIPPED],
        relative_path=relative_path,
        evidence={"link_type": link_type},
        remediation="Replace the symbolic link or junction with a real file or "
        "directory if it should be part of the dataset.",
    )


# ---------------------------------------------------------------------------
# Root level
# ---------------------------------------------------------------------------


def _discover_root_class_only(dataset_root: Path, state: _DiscoveryState) -> None:
    """Discover a ``class-only`` (``<class>/<image>``) dataset root.

    Reuses :func:`_discover_split` unchanged, treating ``dataset_root``
    itself as the single implicit ``train`` split -- every class-subtree
    walk, portability check, link/junction/cycle protection, and candidate
    classification is identical to the split-class layout's; only the
    root-level dispatch (which directory names are "splits") differs.
    """
    enumeration = _discover_split(dataset_root, "train", state)
    state.class_dirs_by_split["train"] = enumeration.class_names
    state.split_direct_level_complete["train"] = enumeration.direct_level_complete
    if enumeration.direct_level_complete and not enumeration.class_names:
        state.findings.append(
            Finding(
                code=codes.SPLIT_TRAIN_HAS_NO_CLASSES,
                severity=Severity.ERROR,
                category=Category.STRUCTURE,
                message=codes.DEFAULT_MESSAGES[codes.SPLIT_TRAIN_HAS_NO_CLASSES],
                relative_path=None,
                remediation="Add at least one class subdirectory to the dataset root.",
            )
        )
    # No cross-split comparison: class-only datasets have exactly one
    # (implicit) split, so SPLIT_CLASS_MISSING_FROM_TRAIN/_OPTIONAL_SPLIT
    # can never apply.


def _discover_root(dataset_root: Path, state: _DiscoveryState) -> None:
    listing = _list_dir(dataset_root, None, state)
    if listing is None:
        # _list_dir already recorded a ScanError explaining exactly why the
        # root could not even be listed; we genuinely don't know whether
        # 'train' exists, so we must not also claim it is missing.
        return
    entries, _root_fully_representable = listing

    state.findings.extend(_portability_findings(entries, None))

    split_dir_entries: dict[str, os.DirEntry[str]] = {}
    train_resolved = False

    for entry in entries:
        name = entry.name
        try:
            kind = _classify(entry)
        except OSError as exc:
            state.scan_errors.append(_scan_error_for_exception(exc, name, "stat"))
            if name == "train":
                # We don't know what 'train' actually is -- do not also
                # claim it is missing on top of the ScanError.
                train_resolved = True
            continue

        if kind in _LINK_KINDS:
            state.findings.append(_link_skipped_finding(name, kind))
            continue

        if name == "train":
            if kind == "dir":
                split_dir_entries["train"] = entry
            else:
                state.findings.append(
                    Finding(
                        code=codes.SPLIT_TRAIN_NOT_A_DIRECTORY,
                        severity=Severity.ERROR,
                        category=Category.STRUCTURE,
                        message=codes.DEFAULT_MESSAGES[codes.SPLIT_TRAIN_NOT_A_DIRECTORY],
                        relative_path="train",
                        remediation="Remove 'train' and create it as a directory of "
                        "class subdirectories.",
                    )
                )
            train_resolved = True
            continue

        if name in _OPTIONAL_SPLITS:
            if kind == "dir":
                split_dir_entries[name] = entry
            else:
                state.findings.append(
                    Finding(
                        code=codes.SPLIT_OPTIONAL_SPLIT_NOT_A_DIRECTORY,
                        severity=Severity.ERROR,
                        category=Category.STRUCTURE,
                        message=codes.DEFAULT_MESSAGES[
                            codes.SPLIT_OPTIONAL_SPLIT_NOT_A_DIRECTORY
                        ],
                        relative_path=name,
                        remediation=f"Remove '{name}' or create it as a directory of "
                        "class subdirectories.",
                    )
                )
            continue

        if kind == "dir":
            state.findings.append(
                Finding(
                    code=codes.SPLIT_UNRECOGNIZED_TOP_LEVEL_DIRECTORY,
                    severity=Severity.WARNING,
                    category=Category.STRUCTURE,
                    message=codes.DEFAULT_MESSAGES[
                        codes.SPLIT_UNRECOGNIZED_TOP_LEVEL_DIRECTORY
                    ],
                    relative_path=name,
                    remediation="Remove or rename this directory to 'train', "
                    "'validation', or 'test' if it belongs in the dataset.",
                )
            )
            continue

        if kind == "file" and _is_candidate_extension(name):
            state.findings.append(
                Finding(
                    code=codes.SPLIT_IMAGE_FILE_AT_DATASET_ROOT,
                    severity=Severity.WARNING,
                    category=Category.STRUCTURE,
                    message=codes.DEFAULT_MESSAGES[codes.SPLIT_IMAGE_FILE_AT_DATASET_ROOT],
                    relative_path=name,
                    remediation="Move this file into 'train/<class>/' (or the "
                    "appropriate split and class).",
                )
            )
        # Any other file is silently ignored: no rule in v1 requires
        # flagging it.

    if not train_resolved:
        state.findings.append(
            Finding(
                code=codes.SPLIT_TRAIN_MISSING,
                severity=Severity.ERROR,
                category=Category.STRUCTURE,
                message=codes.DEFAULT_MESSAGES[codes.SPLIT_TRAIN_MISSING],
                remediation="Create a 'train' directory with one subdirectory per class.",
            )
        )

    for split_name, split_entry in split_dir_entries.items():
        split_path = Path(split_entry.path)
        enumeration = _discover_split(split_path, split_name, state)
        state.class_dirs_by_split[split_name] = enumeration.class_names
        state.split_direct_level_complete[split_name] = enumeration.direct_level_complete
        if (
            split_name == "train"
            and enumeration.direct_level_complete
            and not enumeration.class_names
        ):
            state.findings.append(
                Finding(
                    code=codes.SPLIT_TRAIN_HAS_NO_CLASSES,
                    severity=Severity.ERROR,
                    category=Category.STRUCTURE,
                    message=codes.DEFAULT_MESSAGES[codes.SPLIT_TRAIN_HAS_NO_CLASSES],
                    relative_path="train",
                    remediation="Add at least one class subdirectory under 'train'.",
                )
            )

    _check_cross_split_classes(state)


def _check_cross_split_classes(state: _DiscoveryState) -> None:
    train_complete = state.split_direct_level_complete.get("train", False)
    train_classes = state.class_dirs_by_split.get("train", set())

    for split in _OPTIONAL_SPLITS:
        if split not in state.class_dirs_by_split:
            continue
        if not (train_complete and state.split_direct_level_complete.get(split, False)):
            # Either side's direct-level listing was incomplete: the known
            # class sets might be missing an entry, so any missing/extra
            # comparison would risk being a false claim. Skip it entirely.
            continue

        split_classes = state.class_dirs_by_split[split]

        for extra in sorted(split_classes - train_classes):
            state.findings.append(
                Finding(
                    code=codes.SPLIT_CLASS_MISSING_FROM_TRAIN,
                    severity=Severity.ERROR,
                    category=Category.STRUCTURE,
                    message=codes.DEFAULT_MESSAGES[codes.SPLIT_CLASS_MISSING_FROM_TRAIN],
                    relative_path=f"{split}/{extra}",
                    remediation=f"Add a '{extra}' class under 'train', or remove it "
                    f"from '{split}'.",
                )
            )

        for missing in sorted(train_classes - split_classes):
            state.findings.append(
                Finding(
                    code=codes.SPLIT_CLASS_MISSING_FROM_OPTIONAL_SPLIT,
                    severity=Severity.WARNING,
                    category=Category.STRUCTURE,
                    message=codes.DEFAULT_MESSAGES[codes.SPLIT_CLASS_MISSING_FROM_OPTIONAL_SPLIT],
                    relative_path=split,
                    evidence={"class_name": missing},
                    remediation=f"Add a '{missing}' class under '{split}', or accept it "
                    "will not be evaluated there.",
                )
            )


# ---------------------------------------------------------------------------
# Split level
# ---------------------------------------------------------------------------


def _discover_split(
    split_path: Path, split_name: str, state: _DiscoveryState
) -> _SplitEnumeration:
    listing = _list_dir(split_path, split_name, state)
    if listing is None:
        return _SplitEnumeration(set(), False)
    entries, direct_level_complete = listing

    state.findings.extend(_portability_findings(entries, split_name))

    class_names: set[str] = set()

    for entry in entries:
        relative = _join(split_name, entry.name)
        try:
            kind = _classify(entry)
        except OSError as exc:
            state.scan_errors.append(_scan_error_for_exception(exc, relative, "stat"))
            direct_level_complete = False
            continue

        if kind in _LINK_KINDS:
            state.findings.append(_link_skipped_finding(relative, kind))
            continue

        if kind == "dir":
            class_name = entry.name
            class_path = Path(entry.path)
            candidate_count_before = len(state.candidates)
            subtree_complete = _discover_class_subtree(
                class_path, relative, split_name, class_name, state
            )
            state.class_subtree_complete[(split_name, class_name)] = subtree_complete
            class_names.add(class_name)
            candidate_count = len(state.candidates) - candidate_count_before
            if subtree_complete and candidate_count == 0:
                state.findings.append(
                    Finding(
                        code=codes.SPLIT_EMPTY_CLASS,
                        severity=Severity.ERROR if split_name == "train" else Severity.WARNING,
                        category=Category.STRUCTURE,
                        message=codes.DEFAULT_MESSAGES[codes.SPLIT_EMPTY_CLASS],
                        relative_path=relative,
                        remediation="Add candidate image files under this class, or remove it.",
                    )
                )
            continue

        if kind == "file" and _is_candidate_extension(entry.name):
            state.findings.append(
                Finding(
                    code=codes.SPLIT_FILE_DIRECTLY_IN_SPLIT,
                    severity=Severity.WARNING,
                    category=Category.STRUCTURE,
                    message=codes.DEFAULT_MESSAGES[codes.SPLIT_FILE_DIRECTLY_IN_SPLIT],
                    relative_path=relative,
                    remediation=f"Move this file into a class directory under '{split_name}'.",
                )
            )
        # Any other file is silently ignored.

    return _SplitEnumeration(class_names, direct_level_complete)


# ---------------------------------------------------------------------------
# Class subtree (recursive: nested directories stay in the same class)
# ---------------------------------------------------------------------------


def _discover_class_subtree(
    dir_path: Path,
    relative_dir: str,
    split_name: str,
    class_name: str,
    state: _DiscoveryState,
) -> bool:
    """Recursively discover candidates under one class's subtree.

    Returns ``True`` iff this entire subtree (this directory and every
    nested directory within it) was successfully enumerated -- i.e. no
    ``ScanError`` was recorded anywhere within it. The caller uses this to
    decide whether a zero candidate count means "confirmed empty" or
    merely "not fully examined".
    """
    listing = _list_dir(dir_path, relative_dir, state)
    if listing is None:
        return False
    entries, complete = listing

    state.findings.extend(_portability_findings(entries, relative_dir))

    for entry in entries:
        relative = _join(relative_dir, entry.name)
        try:
            kind = _classify(entry)
        except OSError as exc:
            state.scan_errors.append(_scan_error_for_exception(exc, relative, "stat"))
            complete = False
            continue

        if kind in _LINK_KINDS:
            state.findings.append(_link_skipped_finding(relative, kind))
            continue

        if kind == "dir":
            child_complete = _discover_class_subtree(
                Path(entry.path), relative, split_name, class_name, state
            )
            complete = complete and child_complete
            continue

        if kind == "file":
            extension = Path(entry.name).suffix.lower()
            if extension in CANDIDATE_EXTENSIONS:
                state.candidates.append(
                    DiscoveredImageCandidate(
                        absolute_path=Path(entry.path),
                        relative_path=relative,
                        split=split_name,
                        class_name=class_name,
                        extension=extension,
                    )
                )
            else:
                state.findings.append(
                    Finding(
                        code=codes.IMG_UNSUPPORTED_EXTENSION,
                        severity=Severity.WARNING,
                        category=Category.INTEGRITY,
                        message=codes.DEFAULT_MESSAGES[codes.IMG_UNSUPPORTED_EXTENSION],
                        relative_path=relative,
                        remediation="Remove this file or convert it to a supported format "
                        "(.jpg, .jpeg, .png, .webp).",
                    )
                )
            continue

        # kind == "other": a non-regular entry (socket, FIFO, device, ...).
        # Flagged, never opened.
        state.findings.append(
            Finding(
                code=codes.IMG_NON_REGULAR_ENTRY,
                severity=Severity.WARNING,
                category=Category.INTEGRITY,
                message=codes.DEFAULT_MESSAGES[codes.IMG_NON_REGULAR_ENTRY],
                relative_path=relative,
                remediation="Remove this entry; it is not a regular file and will "
                "never be opened.",
            )
        )

    return complete
